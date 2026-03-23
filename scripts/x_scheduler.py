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
    JOB_DISCOVERY_HOUR_ET,
    LINKEDIN_POST_HOUR_PT,
    PACIFIC_TZ,
    SYNTER_CAMPAIGN_HOUR_PT,
    X_POST_HOURS_PT,
    date_str,
    ensure_timezone,
    should_enrich_now,
    should_job_discovery_now,
    should_linkedin_post_now,
    should_followup_now,
    should_listicle_outreach_now,
    should_post_now,
    should_synter_campaign_now,
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


SYNTER_CAMPAIGN_ENABLED = os.environ.get("SYNTER_CAMPAIGN_ENABLED", "true").lower() != "false"
LINKEDIN_NATIVE_ENABLED = os.environ.get("LINKEDIN_NATIVE_POSTING_ENABLED", "true").lower() != "false"
MCP_REPLY_ENABLED = os.environ.get("X_MCP_REPLY_SCANNER_ENABLED", "true").lower() != "false"
MCP_REPLY_MAX = int(os.environ.get("X_MCP_REPLY_MAX_PER_RUN", "5"))


def run_synter_campaign():
    """Post next Synter campaign item to LinkedIn (org) + X (@synterai) with ad images."""
    try:
        from engine.x.synter_campaign_post import load_calendar, load_posted, get_next_post, post_campaign

        calendar = load_calendar()
        posted = load_posted()
        post = get_next_post(calendar, posted)

        if not post:
            logger.info("Synter campaign calendar exhausted, all posts sent")
            return

        result = post_campaign(post)
        li = result.get("linkedin", {})
        x = result.get("x", {})
        logger.info(
            "Synter campaign %s: LinkedIn=%s (%s) | X=%s (%s)",
            result.get("post_id"),
            "✅" if li.get("success") else "❌",
            li.get("post_urn") or li.get("error", ""),
            "✅" if x.get("success") else "❌",
            x.get("url") or x.get("error", ""),
        )

    except Exception as e:
        logger.error("Synter campaign post failed: %s", e, exc_info=True)


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


JOB_DISCOVERY_ENABLED = os.environ.get("JOB_DISCOVERY_ENABLED", "true").lower() != "false"
JOB_DISCOVERY_LIMIT = int(os.environ.get("JOB_DISCOVERY_LIMIT", "30"))
LISTICLE_OUTREACH_ENABLED = os.environ.get("LISTICLE_OUTREACH_ENABLED", "true").lower() != "false"
FOLLOWUP_ENABLED = os.environ.get("LISTICLE_FOLLOWUP_ENABLED", "true").lower() != "false"


def run_job_discovery():
    """Daily geo-routed job discovery → enrichment → Smartlead outreach.

    Runs the geo_pipeline.py script which discovers leads across US, CA,
    UK, DE, NL, FR, IE, AU, NZ and routes them to timezone-appropriate
    Smartlead campaigns (Americas/EU/APAC).
    """
    try:
        import subprocess
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        geo_script = os.path.join(scripts_dir, "geo_pipeline.py")
        result = subprocess.run(
            [sys.executable, geo_script],
            capture_output=True, text=True, timeout=1800,  # 30 min for full geo sweep
        )
        logger.info("geo pipeline stdout: %s", result.stdout[-1000:] if result.stdout else "(empty)")
        if result.returncode != 0:
            logger.error("geo pipeline stderr: %s", result.stderr[-500:] if result.stderr else "(empty)")
    except Exception as e:
        logger.error("geo pipeline failed: %s", e, exc_info=True)

    # Also run signal-based discovery (fundraising, job changes, tech stack)
    try:
        logger.info("running signal-based discovery pipeline...")
        signal_result = subprocess.run(
            [sys.executable, "-m", "engine.signals.pipeline", "--limit", "30"],
            capture_output=True, text=True, timeout=600,
        )
        logger.info("signal pipeline stdout: %s", signal_result.stdout[-500:] if signal_result.stdout else "(empty)")
        if signal_result.returncode != 0:
            logger.error("signal pipeline stderr: %s", signal_result.stderr[-500:] if signal_result.stderr else "(empty)")
    except Exception as e:
        logger.error("signal pipeline failed: %s", e, exc_info=True)


def run_listicle_outreach():
    """Weekly listicle + podcast discovery → enrichment → outreach pipeline."""
    try:
        from engine.config import Settings
        from engine.clients.hunter import HunterClient
        from engine.db.database import init_db
        from engine.listicle.scraper import discover_via_serper, store_targets
        from engine.listicle.enricher import enrich_targets
        from engine.listicle.outreach import send_outreach

        settings = Settings()
        SessionFactory = init_db(settings.database_path)
        session = SessionFactory()

        serper_key = getattr(settings, "serper_api_key", "")
        if not serper_key:
            logger.warning("listicle outreach skipped: SERPER_API_KEY not set")
            return

        # Step 1: Discover new targets (listicles + podcasts)
        for target_type in ("listicle", "podcast"):
            targets = discover_via_serper(serper_key, target_type=target_type)
            stats = store_targets(session, targets)
            logger.info("discovery [%s]: %d new, %d existing", target_type, stats["new"], stats["existing"])

        # Step 2: Enrich with editor/host contacts
        if settings.hunter_api_key:
            hunter = HunterClient(settings)
            for target_type in ("listicle", "podcast"):
                e_stats = enrich_targets(session, hunter, limit=30, target_type=target_type)
                logger.info("enrichment [%s]: %d contacts found", target_type, e_stats["enriched"])

        # Step 3: Send outreach via Resend
        if settings.resend_api_key:
            for target_type in ("listicle", "podcast"):
                o_stats = send_outreach(session, settings, limit=20, target_type=target_type)
                logger.info("outreach [%s]: %d sent, %d failed", target_type, o_stats["sent"], o_stats["failed"])
        else:
            logger.warning("listicle outreach skipped send: RESEND_API_KEY not set")

        session.close()

    except Exception as e:
        logger.error("listicle outreach pipeline failed: %s", e, exc_info=True)


def run_listicle_followups():
    """Daily follow-up check — sends follow-up #1 (3 days) and #2 (6 days)."""
    try:
        from engine.config import Settings
        from engine.db.database import init_db
        from engine.listicle.outreach import send_followups

        settings = Settings()
        if not settings.resend_api_key:
            logger.warning("listicle followups skipped: RESEND_API_KEY not set")
            return

        SessionFactory = init_db(settings.database_path)
        session = SessionFactory()
        stats = send_followups(session, settings, limit=30)
        logger.info(
            "followups: fu1=%d, fu2=%d, failed=%d",
            stats["follow_up_1_sent"], stats["follow_up_2_sent"], stats["failed"],
        )
        session.close()

    except Exception as e:
        logger.error("listicle followups failed: %s", e, exc_info=True)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="X Growth Engine Scheduler")
    parser.add_argument("--once", choices=["post", "scan", "linkedin", "mcp-replies", "listicle", "followups", "job-discovery", "synter-campaign"], help="Run once and exit")
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
    if args.once == "listicle":
        run_listicle_outreach()
        return
    if args.once == "followups":
        run_listicle_followups()
        return
    if args.once == "job-discovery":
        run_job_discovery()
        return
    if args.once == "synter-campaign":
        run_synter_campaign()
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
    logger.info("  Synter campaign (LI+X): Tuesdays at %d:00 PT (%s)", SYNTER_CAMPAIGN_HOUR_PT, "enabled" if SYNTER_CAMPAIGN_ENABLED else "disabled")
    logger.info("  enrichment pipeline: Mon-Fri at %d:00 ET", ENRICHMENT_HOUR_ET)
    logger.info("  job discovery: Mon-Fri at %d:00 ET (%s)", JOB_DISCOVERY_HOUR_ET, "enabled" if JOB_DISCOVERY_ENABLED else "disabled")
    logger.info("  listicle/podcast outreach: Tuesdays at 10:00 ET (%s)", "enabled" if LISTICLE_OUTREACH_ENABLED else "disabled")
    logger.info("  follow-up emails: Mon-Fri at 11:00 ET (%s)", "enabled" if FOLLOWUP_ENABLED else "disabled")

    last_post_slot: str | None = None
    last_scan_time: float = 0  # scan immediately on startup
    last_mcp_reply_time: float = 0  # scan immediately on startup
    last_li_date: str | None = None
    last_enrich_date: str | None = None
    last_job_date: str | None = None
    last_listicle_date: str | None = None
    last_followup_date: str | None = None
    last_campaign_date: str | None = None

    while running:
        try:
            if should_post_now(last_post_slot):
                now = ensure_timezone(None, PACIFIC_TZ)
                logger.info("X posting (%s PT)...", now.strftime("%Y-%m-%d %H:%M"))
                run_post()
                last_post_slot = slot_key(now, PACIFIC_TZ)

            if SYNTER_CAMPAIGN_ENABLED and should_synter_campaign_now(last_campaign_date):
                logger.info("Synter campaign posting (LinkedIn + X @synterai)...")
                run_synter_campaign()
                last_campaign_date = date_str(None, PACIFIC_TZ)

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

            if JOB_DISCOVERY_ENABLED and should_job_discovery_now(last_job_date):
                logger.info("running job discovery pipeline (limit=%d)...", JOB_DISCOVERY_LIMIT)
                run_job_discovery()
                last_job_date = date_str(None, EASTERN_TZ)

            if LISTICLE_OUTREACH_ENABLED and should_listicle_outreach_now(last_listicle_date):
                logger.info("running weekly listicle/podcast outreach...")
                run_listicle_outreach()
                last_listicle_date = date_str(None, EASTERN_TZ)

            if FOLLOWUP_ENABLED and should_followup_now(last_followup_date):
                logger.info("running daily follow-up check...")
                run_listicle_followups()
                last_followup_date = date_str(None, EASTERN_TZ)

        except Exception as e:
            logger.error("scheduler loop error: %s", e, exc_info=True)

        time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("scheduler stopped")


if __name__ == "__main__":
    main()
