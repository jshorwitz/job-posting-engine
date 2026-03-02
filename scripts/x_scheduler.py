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


def run_post():
    """Post next scheduled item from content calendar."""
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

    except Exception as e:
        logger.error("post failed: %s", e, exc_info=True)


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
    parser.add_argument("--once", choices=["post", "scan"], help="Run once and exit")
    args = parser.parse_args()

    if args.once == "post":
        run_post()
        return
    if args.once == "scan":
        run_scan()
        return

    # Long-lived scheduler loop
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("received signal %s, shutting down...", sig)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info("X Growth Engine scheduler started")
    logger.info("  post times (UTC): %s", POST_HOURS_UTC)
    logger.info("  scan interval: every %d hours", SCAN_INTERVAL_HOURS)

    last_post_hour: int | None = None
    last_scan_time: float = 0  # scan immediately on startup

    while running:
        try:
            if should_post_now(last_post_hour):
                now = datetime.now(timezone.utc)
                logger.info("posting (hour=%d UTC)...", now.hour)
                run_post()
                last_post_hour = now.hour

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
