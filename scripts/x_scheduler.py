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

from engine.x.time_utils import (
    EASTERN_TZ,
    ENRICHMENT_HOUR_ET,
    LINKEDIN_POST_HOUR_PT,
    PACIFIC_TZ,
    X_POST_HOURS_PT,
    date_str,
    ensure_timezone,
    should_enrich_now,
    should_linkedin_post_now,
    should_post_now,
    slot_key,
)


SCAN_INTERVAL_HOURS = int(os.environ.get("X_ENGAGEMENT_SCAN_INTERVAL_HOURS", "4"))
MCP_REPLY_INTERVAL_HOURS = int(os.environ.get("X_MCP_REPLY_INTERVAL_HOURS", "2"))
POLL_INTERVAL_SECONDS = 60  # Check every minute


def should_scan_now(last_scan_time: float) -> bool:
    """Check if enough time has passed since last scan."""
    elapsed = time.time() - last_scan_time
    return elapsed >= SCAN_INTERVAL_HOURS * 3600


LINKEDIN_CROSSPOST_ENABLED = os.environ.get("X_LINKEDIN_CROSSPOST_ENABLED", "true").lower() != "false"


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


LINKEDIN_NATIVE_ENABLED = os.environ.get("LINKEDIN_NATIVE_POSTING_ENABLED", "true").lower() != "false"
MCP_REPLY_ENABLED = os.environ.get("X_MCP_REPLY_SCANNER_ENABLED", "true").lower() != "false"
MCP_REPLY_MAX = int(os.environ.get("X_MCP_REPLY_MAX_PER_RUN", "5"))


def run_linkedin_post():
    """Post next item from the LinkedIn content calendar with generated image."""
    try:
        from engine.x.linkedin_scheduler import load_calendar, load_posted, get_next_post, post_linkedin

        calendar = load_calendar()
        posted = load_posted()
        post_id, post = get_next_post(calendar, posted)

        if not post:
            logger.info("LinkedIn calendar exhausted, all posts sent")
            return

        result = post_linkedin(post_id, post)
        if result.get("status") == "sent":
            logger.info("LinkedIn native post %s sent: %s (image=%s)",
                        post_id, result.get("linkedin_post_id", ""), result.get("has_image"))
        else:
            logger.warning("LinkedIn native post %s failed: %s", post_id, result.get("error", ""))

    except Exception as e:
        logger.error("LinkedIn native post failed: %s", e, exc_info=True)


def should_mcp_reply_now(last_mcp_reply_time: float) -> bool:
    """Check if enough time has passed since last MCP reply scan."""
    elapsed = time.time() - last_mcp_reply_time
    return elapsed >= MCP_REPLY_INTERVAL_HOURS * 3600


def run_mcp_replies():
    """Scan for Claude+Facebook Ads+MCP tweets and reply."""
    try:
        from engine.x.mcp_reply_scanner import run_scan_and_reply

        result = run_scan_and_reply(max_replies=MCP_REPLY_MAX)
        sent = [r for r in result.get("replies", []) if r.get("status") == "sent"]
        logger.info(
            "MCP reply scan: %d candidates, %d replies sent",
            result.get("candidates_found", 0), len(sent),
        )
        for r in sent:
            logger.info("  replied to %s: %s", r.get("author"), r.get("reply_url"))

    except Exception as e:
        logger.error("MCP reply scan failed: %s", e, exc_info=True)


def run_enrichment():
    """Run the enrichment + Loops export pipeline."""
    try:
        from engine.config import Settings
        from engine.pipeline import run_enrichment as _run_enrichment

        settings = Settings()
        stats = _run_enrichment(settings=settings, export_target="loops")
        logger.info("enrichment complete: %s", stats)
    except Exception as e:
        logger.error("enrichment pipeline failed: %s", e, exc_info=True)


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
    parser.add_argument("--once", choices=["post", "scan", "linkedin", "mcp-replies"], help="Run once and exit")
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
    if args.once == "mcp-replies":
        run_mcp_replies()
        return

    # Long-lived scheduler loop
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("received signal %s, shutting down...", sig)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info("Growth Engine scheduler started")
    logger.info("  X post times (PT): %s", X_POST_HOURS_PT)
    logger.info("  LinkedIn post: Tue-Thu at %d:00 PT", LINKEDIN_POST_HOUR_PT)
    logger.info("  scan interval: every %d hours", SCAN_INTERVAL_HOURS)
    logger.info("  MCP reply scan: every %d hours (%s)", MCP_REPLY_INTERVAL_HOURS, "enabled" if MCP_REPLY_ENABLED else "disabled")
    logger.info("  LinkedIn native posting: %s", "enabled" if LINKEDIN_NATIVE_ENABLED else "disabled")
    logger.info("  enrichment pipeline: Mon-Fri at %d:00 ET", ENRICHMENT_HOUR_ET)

    last_post_slot: str | None = None
    last_scan_time: float = 0  # scan immediately on startup
    last_mcp_reply_time: float = 0  # scan immediately on startup
    last_li_date: str | None = None
    last_enrich_date: str | None = None

    while running:
        try:
            if should_post_now(last_post_slot):
                now = ensure_timezone(None, PACIFIC_TZ)
                logger.info("X posting (%s PT)...", now.strftime("%Y-%m-%d %H:%M"))
                run_post()
                last_post_slot = slot_key(now, PACIFIC_TZ)

            if LINKEDIN_NATIVE_ENABLED and should_linkedin_post_now(last_li_date):
                logger.info("LinkedIn native posting...")
                run_linkedin_post()
                last_li_date = date_str(None, PACIFIC_TZ)

            if should_scan_now(last_scan_time):
                logger.info("scanning for engagement...")
                run_scan()
                last_scan_time = time.time()

            if MCP_REPLY_ENABLED and should_mcp_reply_now(last_mcp_reply_time):
                logger.info("scanning for Claude+Facebook Ads+MCP tweets...")
                run_mcp_replies()
                last_mcp_reply_time = time.time()

            if should_enrich_now(last_enrich_date):
                logger.info("running enrichment pipeline...")
                run_enrichment()
                last_enrich_date = date_str(None, EASTERN_TZ)

        except Exception as e:
            logger.error("scheduler loop error: %s", e, exc_info=True)

        time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("scheduler stopped")


if __name__ == "__main__":
    main()
