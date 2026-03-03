#!/usr/bin/env python3
"""
Lightweight scheduler for the X Growth Engine.

Runs as a long-lived Railway service (not a cron job).
Posts from the content calendar 3x daily and scans for engagement every 4 hours.

Usage:
    python scripts/x_scheduler.py              # Run scheduler (long-lived)
    python scripts/x_scheduler.py --once post  # Run once and exit (for testing)
    python scripts/x_scheduler.py --once scan  # Run once and exit (for testing)
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("x_scheduler")

# Post times in UTC (9am PT = 17:00 UTC, 2pm PT = 22:00 UTC, 4pm PT = 00:00 UTC)
POST_HOURS_UTC = [17, 22, 0]
SCAN_INTERVAL_HOURS = int(os.environ.get("X_ENGAGEMENT_SCAN_INTERVAL_HOURS", "4"))
POLL_INTERVAL_SECONDS = 60  # Check every minute


def should_post_now(last_post_hour: int | None) -> bool:
    """Check if current hour matches a post time and hasn't been posted this hour."""
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    if current_hour in POST_HOURS_UTC and current_hour != last_post_hour:
        return True
    return False


def should_scan_now(last_scan_time: float) -> bool:
    """Check if enough time has passed since last scan."""
    elapsed = time.time() - last_scan_time
    return elapsed >= SCAN_INTERVAL_HOURS * 3600


LINKEDIN_CROSSPOST_ENABLED = os.environ.get("X_LINKEDIN_CROSSPOST_ENABLED", "true").lower() != "false"
LINKEDIN_NATIVE_ENABLED = os.environ.get("LINKEDIN_CONTENT_POSTER_ENABLED", "true").lower() != "false"
LINKEDIN_POST_HOUR_UTC = 17  # 9am PT


def run_post():
    """Post next scheduled item from content calendar, then cross-post to LinkedIn."""
    try:
        from engine.x.scheduled_post import (
            load_calendar, load_posted_log, save_posted_log,
            get_next_post, get_oauth_session, post_tweet,
        )

        calendar = load_calendar()
        posted = load_posted_log()
        post_id, post = get_next_post(calendar, posted)

        if not post:
            logger.info("content calendar exhausted, all posts sent")
            return

        text = post.get("text", "")
        if len(text) > 280:
            logger.warning("skipping %s: exceeds 280 chars (%d)", post_id, len(text))
            return

        oauth = get_oauth_session()
        result = post_tweet(oauth, text)
        tid = result.get("data", {}).get("id", "")

        posted.add(post_id)
        save_posted_log(posted)

        logger.info(
            "posted %s (%s %s): https://x.com/JSHorwitz/status/%s",
            post_id, post.get("day"), post.get("type"), tid,
        )

        # Auto cross-post to LinkedIn if enabled and post type is eligible
        if LINKEDIN_CROSSPOST_ENABLED:
            _crosspost_to_linkedin(post_id, post)

    except Exception as e:
        logger.error("post failed: %s", e, exc_info=True)


def _crosspost_to_linkedin(post_id: str, post: dict):
    """Cross-post an X post to LinkedIn personal profile."""
    try:
        from engine.x.linkedin_crosspost import (
            CROSSPOST_TYPES, adapt_for_linkedin, post_to_linkedin,
            load_linkedin_posted, save_linkedin_posted,
        )

        if post.get("type", "") not in CROSSPOST_TYPES:
            logger.debug("skipping LinkedIn cross-post for %s (type=%s)", post_id, post.get("type"))
            return

        li_posted = load_linkedin_posted()
        if post_id in li_posted:
            return

        from engine.x.linkedin_crosspost import get_linkedin_auth, _retry_with_refresh
        try:
            token, org_urn = get_linkedin_auth()
        except Exception as e:
            logger.debug("LinkedIn cross-post skipped: %s", e)
            return

        adapted = adapt_for_linkedin(post)
        result = _retry_with_refresh(post_to_linkedin, token, org_urn, adapted)

        if result.get("success"):
            li_posted.add(post_id)
            save_linkedin_posted(li_posted)
            logger.info("cross-posted %s to LinkedIn: %s", post_id, result.get("post_id", ""))
        else:
            logger.warning("LinkedIn cross-post failed for %s: %s", post_id, result.get("error", ""))

    except Exception as e:
        logger.error("LinkedIn cross-post error for %s: %s", post_id, e)


def should_post_linkedin_now(last_linkedin_hour: int | None) -> bool:
    """Check if current time is LinkedIn posting time (9am PT = 17:00 UTC, Tue-Thu only)."""
    now = datetime.now(timezone.utc)
    if now.weekday() not in (1, 2, 3):  # Tue=1, Wed=2, Thu=3
        return False
    if now.hour == LINKEDIN_POST_HOUR_UTC and now.hour != last_linkedin_hour:
        return True
    return False


def run_linkedin_post():
    """Post next scheduled item from the LinkedIn-native content calendar."""
    try:
        from engine.x.linkedin_scheduled_post import (
            load_calendar, load_posted_log, save_posted_log,
            get_next_post, LINKEDIN_DAYS,
        )
        from engine.x.linkedin_generate_image import generate_image
        from engine.x.linkedin_org_post import post_to_linkedin_native

        calendar = load_calendar()
        posted = load_posted_log()
        post_id, post = get_next_post(calendar, posted)

        if not post:
            logger.info("LinkedIn content calendar exhausted, all posts sent")
            return

        # Generate image if the post has an image_prompt
        image_path = None
        image_prompt = post.get("image_prompt")
        if image_prompt:
            logger.info("generating LinkedIn image for %s...", post_id)
            img_result = generate_image(image_prompt, output_name=post_id.replace("/", "_"))
            if img_result.get("success"):
                image_path = img_result["image_path"]
                logger.info("image saved: %s", image_path)
            else:
                logger.warning("image generation failed: %s (posting without image)", img_result.get("error"))

        # Post to LinkedIn
        text = post.get("text", "")
        result = post_to_linkedin_native(text, image_path=image_path)

        if result.get("success"):
            posted[post_id] = {
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "post_urn": result.get("post_urn", ""),
                "image_path": image_path,
            }
            save_posted_log(posted)
            logger.info(
                "posted to LinkedIn: %s (%s %s) %s",
                post_id, post.get("day"), post.get("type"),
                result.get("post_urn", ""),
            )
        else:
            logger.warning("LinkedIn post failed for %s: %s", post_id, result.get("error"))

    except Exception as e:
        logger.error("LinkedIn native post failed: %s", e, exc_info=True)


def run_scan():
    """Scan for engagement opportunities."""
    try:
        from engine.x.engagement_scanner import run_scan as _run_scan, save_candidates

        candidates = _run_scan()
        scan_data = {
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
        save_candidates(scan_data)

        if candidates:
            logger.info("scan found %d candidates, top: @%s (%d likes)",
                        len(candidates), candidates[0]["author_username"], candidates[0]["likes"])
        else:
            logger.info("scan found 0 candidates matching filters")

    except Exception as e:
        logger.error("scan failed: %s", e, exc_info=True)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="X Growth Engine Scheduler")
    parser.add_argument("--once", choices=["post", "scan", "linkedin"], help="Run once and exit")
    args = parser.parse_args()

    if args.once == "post":
        run_post()
        return
    if args.once == "scan":
        run_scan()
        return
    if args.once == "linkedin":
        run_linkedin_post()
        return

    # Long-lived scheduler loop
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("received signal %s, shutting down...", sig)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info("X + LinkedIn Growth Engine scheduler started")
    logger.info("  X post times (UTC): %s", POST_HOURS_UTC)
    logger.info("  X scan interval: every %d hours", SCAN_INTERVAL_HOURS)
    logger.info("  LinkedIn native posting: %s (Tue-Thu at 17:00 UTC / 9am PT)",
                "enabled" if LINKEDIN_NATIVE_ENABLED else "disabled")

    last_post_hour: int | None = None
    last_linkedin_hour: int | None = None
    last_scan_time: float = 0  # scan immediately on startup

    while running:
        try:
            if should_post_now(last_post_hour):
                now = datetime.now(timezone.utc)
                logger.info("posting to X (hour=%d UTC)...", now.hour)
                run_post()
                last_post_hour = now.hour

            if LINKEDIN_NATIVE_ENABLED and should_post_linkedin_now(last_linkedin_hour):
                now = datetime.now(timezone.utc)
                logger.info("posting to LinkedIn (hour=%d UTC, day=%s)...", now.hour, now.strftime("%A"))
                run_linkedin_post()
                last_linkedin_hour = now.hour

            if should_scan_now(last_scan_time):
                logger.info("scanning for engagement...")
                run_scan()
                last_scan_time = time.time()

        except Exception as e:
            logger.error("scheduler loop error: %s", e, exc_info=True)

        time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("scheduler stopped")


if __name__ == "__main__":
    main()
