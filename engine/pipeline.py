"""Main pipeline — called by cron or `run-engine` CLI command.

Flow:
  1. Init DB
  2. Fetch growth leadership job postings from Sumble
  3. For each new posting:
     a. Deduplicate by job ID (skip if already seen)
     b. Deduplicate by company domain (skip if already contacted)
     c. Find CEO/founder via Sumble People API
     d. Generate personalized message via OpenAI
     e. Send via LinkedIn (InMail / connection request) and/or email
     f. Log result to SQLite
  4. Post Slack summary

Channels (--channel flag):
  - linkedin:  Send via LinkedIn Sales Navigator (default)
  - email:     Send via SMTP (requires email enrichment)
  - both:      LinkedIn + email

LinkedIn outreach types (LINKEDIN_OUTREACH_TYPE env):
  - inmail:      Send InMail via Sales Navigator
  - connection:  Send connection request with note
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.ai.email_writer import generate_outreach_email
from engine.ai.linkedin_writer import generate_connection_note, generate_inmail
from engine.clients.csv_import import load_contacts_csv, load_jobs_csv
from engine.clients.hunter import HunterClient
from engine.clients.slack import post_run_summary
from engine.clients.sumble import SumbleClient
from engine.config import Settings
from engine.db.database import init_db
from engine.db.models import (
    Contact,
    EmailLog,
    EmailStatus,
    JobPosting,
    LinkedInOutreach,
    LinkedInOutreachStatus,
    OutreachType,
)

LOG_PREFIX = "[JobPostingEngine]"


def run(
    settings: Settings,
    csv_jobs: str | None = None,
    csv_contacts: str | None = None,
) -> dict[str, int]:
    """Execute the full pipeline. Returns stats dict.

    Args:
        settings:      Application settings.
        csv_jobs:      Path to CSV file with job postings (bypasses Sumble Jobs API).
        csv_contacts:  Path to CSV file with contacts (bypasses Sumble People API).
    """

    # --- Logging ---
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / "engine.log"),
        ],
    )
    logger = logging.getLogger(__name__)

    channel = settings.outreach_channel.lower()
    li_type = settings.linkedin_outreach_type.lower()
    source = "CSV" if csv_jobs else "Sumble API"

    logger.info("=" * 60)
    logger.info(f"{LOG_PREFIX} Starting")
    logger.info(
        f"  source={source}  query={settings.job_query!r}  dry_run={settings.dry_run}  "
        f"channel={channel}  linkedin_type={li_type}"
    )
    logger.info(f"  max_per_run={settings.max_emails_per_run}")
    logger.info("=" * 60)

    # --- Init ---
    SessionFactory = init_db(settings.database_path)
    session = SessionFactory()
    sumble = SumbleClient(settings) if not csv_jobs else None
    stats = {"sent": 0, "skipped": 0, "failed": 0, "new_jobs": 0}
    contacted_companies: list[str] = []

    # Pre-load contacts from CSV if provided (bypasses Sumble People API)
    csv_contact_map: dict[str, dict] = {}
    if csv_contacts:
        for c in load_contacts_csv(csv_contacts):
            key = (c.get("organization_domain") or c.get("organization_name") or "").lower()
            if key:
                csv_contact_map[key] = c

    # Hunter.io for email enrichment (lazy-init only if email channel used)
    hunter: HunterClient | None = None
    use_linkedin = channel in ("linkedin", "both")
    use_email = channel in ("email", "both")

    if use_email and settings.hunter_api_key:
        hunter = HunterClient(settings)
        logger.info("Hunter.io email enrichment enabled")
    elif use_email:
        logger.warning("Email channel selected but HUNTER_API_KEY not set — emails won't be sent")

    # LinkedIn automation (lazy-init only if needed)
    li_automation = None

    if use_linkedin and not settings.dry_run:
        from engine.outreach.linkedin_sender import LinkedInAutomation
        li_automation = LinkedInAutomation(settings)

    try:
        # ── Step 1: Fetch job postings ───────────────────────────────
        if csv_jobs:
            title_keywords = [
                kw for kw in settings.job_query.split() if len(kw) > 2
            ] or None
            jobs = load_jobs_csv(csv_jobs, title_keywords=title_keywords)
        else:
            technologies = [
                t.strip() for t in settings.job_technologies.split(",") if t.strip()
            ] or None
            countries = [
                c.strip() for c in settings.job_countries.split(",") if c.strip()
            ] or None
            from datetime import timedelta
            since = (
                datetime.now(timezone.utc) - timedelta(days=settings.job_since_days)
            ).strftime("%Y-%m-%d")

            jobs = sumble.find_jobs(
                query=settings.job_query,
                technologies=technologies,
                countries=countries,
                limit=settings.max_emails_per_run * 3,
                since=since,
            )

        for job in jobs:
            if stats["sent"] >= settings.max_emails_per_run:
                logger.info("Max per run reached — stopping.")
                break

            job_id = str(job.get("id", ""))
            org_id = job.get("organization_id")
            org_name = job.get("organization_name", "Unknown")
            org_domain = job.get("organization_domain")
            job_title = job.get("job_title", settings.job_query)
            job_url = job.get("url", "")
            location = job.get("location", "")
            posted_at = job.get("datetime_pulled", "")

            # ── Step 2: Deduplicate by job ID ────────────────────────
            if session.query(JobPosting).filter_by(sumble_job_id=job_id).first():
                logger.debug(f"Already seen job {job_id} @ {org_name}")
                stats["skipped"] += 1
                continue

            # ── Step 3: Deduplicate by company domain ────────────────
            if org_domain:
                # Check email log
                email_dup = (
                    session.query(EmailLog)
                    .filter_by(company_domain=org_domain)
                    .filter(EmailLog.status.in_([EmailStatus.SENT, EmailStatus.SKIPPED]))
                    .first()
                )
                # Check LinkedIn log
                li_dup = (
                    session.query(LinkedInOutreach)
                    .filter_by(company_domain=org_domain)
                    .filter(
                        LinkedInOutreach.status.in_([
                            LinkedInOutreachStatus.SENT,
                            LinkedInOutreachStatus.SKIPPED,
                        ])
                    )
                    .first()
                )
                if email_dup or li_dup:
                    logger.debug(f"Already contacted {org_domain} — skipping")
                    stats["skipped"] += 1
                    continue

            # ── Step 4: Persist job posting ──────────────────────────
            job_record = JobPosting(
                sumble_job_id=job_id,
                company_name=org_name,
                company_domain=org_domain,
                organization_id=org_id,
                job_title=job_title,
                job_url=job_url,
                location=location,
                posted_at=posted_at,
            )
            session.add(job_record)
            session.commit()
            stats["new_jobs"] += 1

            # ── Step 5: Find CEO/founder ─────────────────────────────
            # Check CSV contacts first, then fall back to Sumble API
            csv_key = (org_domain or org_name or "").lower()
            csv_contact = csv_contact_map.get(csv_key)

            if csv_contact:
                ceo = {
                    "id": f"csv-{csv_key}",
                    "name": csv_contact.get("name", ""),
                    "job_title": csv_contact.get("job_title", ""),
                    "linkedin_url": csv_contact.get("linkedin_url", ""),
                }
            elif sumble:
                ceo = sumble.find_ceo(
                    organization_domain=org_domain,
                    organization_id=org_id,
                )
            else:
                logger.info(f"No contact for {org_name} — provide via --csv-contacts")
                ceo = None

            if not ceo:
                logger.info(f"No executive found for {org_name} ({org_domain}) — skipping")
                stats["skipped"] += 1
                continue

            ceo_name = ceo.get("name", "")
            ceo_title = ceo.get("job_title", "")
            ceo_linkedin = ceo.get("linkedin_url", "")
            ceo_person_id = str(ceo.get("id", ""))

            # ── Step 6: Enrich with email via Hunter.io ─────────────
            ceo_email: str | None = None
            email_score: int | None = None

            if hunter and org_domain and ceo_name:
                hunter_result = hunter.find_email(
                    domain=org_domain, full_name=ceo_name
                )
                if hunter_result:
                    ceo_email = hunter_result.get("email")
                    email_score = hunter_result.get("score")
                time.sleep(0.1)  # rate limit courtesy

            # ── Step 7: Upsert contact ───────────────────────────────
            contact = session.query(Contact).filter_by(
                sumble_person_id=ceo_person_id
            ).first()
            if not contact:
                contact = Contact(
                    sumble_person_id=ceo_person_id,
                    company_domain=org_domain,
                    full_name=ceo_name,
                    job_title=ceo_title,
                    email=ceo_email,
                    email_score=email_score,
                    linkedin_url=ceo_linkedin,
                )
                session.add(contact)
                session.commit()
            elif ceo_email and not contact.email:
                contact.email = ceo_email
                contact.email_score = email_score
                session.commit()

            # ── Step 8: LinkedIn outreach ────────────────────────────
            if use_linkedin and ceo_linkedin:
                _handle_linkedin_outreach(
                    settings=settings,
                    session=session,
                    li_automation=li_automation,
                    ceo_name=ceo_name,
                    ceo_linkedin=ceo_linkedin,
                    org_name=org_name,
                    org_domain=org_domain or org_name,
                    job_title=job_title,
                    li_type=li_type,
                    logger=logger,
                )

            # ── Step 9: Email outreach (if channel includes email) ───
            if use_email:
                _handle_email_outreach(
                    settings=settings,
                    session=session,
                    ceo_name=ceo_name,
                    ceo_email=ceo_email,
                    ceo_linkedin=ceo_linkedin,
                    org_name=org_name,
                    org_domain=org_domain or org_name,
                    job_title=job_title,
                    logger=logger,
                )

            stats["sent"] += 1
            contacted_companies.append(org_name)

            # Rate limit courtesy
            time.sleep(RATE_LIMIT_DELAY)

    except Exception as exc:
        logger.exception(f"{LOG_PREFIX} Pipeline error: {exc}")
    finally:
        if li_automation:
            li_automation.close()
        session.close()

    logger.info("=" * 60)
    logger.info(
        f"{LOG_PREFIX} Complete — "
        f"new_jobs={stats['new_jobs']} sent={stats['sent']} "
        f"skipped={stats['skipped']} failed={stats['failed']}"
    )
    logger.info("=" * 60)

    # ── Slack summary ────────────────────────────────────────────────
    post_run_summary(
        webhook_url=settings.slack_webhook_url,
        sent=stats["sent"],
        skipped=stats["skipped"],
        failed=stats["failed"],
        sample_companies=contacted_companies,
    )

    return stats


# ------------------------------------------------------------------
# Channel handlers
# ------------------------------------------------------------------


def _handle_linkedin_outreach(
    *,
    settings: Settings,
    session,
    li_automation,
    ceo_name: str,
    ceo_linkedin: str,
    org_name: str,
    org_domain: str,
    job_title: str,
    li_type: str,
    logger: logging.Logger,
) -> None:
    """Generate and send LinkedIn outreach (InMail or connection request)."""

    if li_type == "connection":
        outreach_type = OutreachType.LINKEDIN_CONNECTION
        note = generate_connection_note(
            settings=settings,
            ceo_name=ceo_name,
            company_name=org_name,
            job_title_hiring=job_title,
        )
        subject = None
        body = note
    else:
        outreach_type = OutreachType.LINKEDIN_INMAIL
        subject, body = generate_inmail(
            settings=settings,
            ceo_name=ceo_name,
            company_name=org_name,
            job_title_hiring=job_title,
            company_domain=org_domain,
        )

    if settings.dry_run:
        logger.info(
            f"[DRY RUN] LinkedIn {li_type} → {ceo_name} @ {org_name}\n"
            f"  LinkedIn: {ceo_linkedin}\n"
            f"  Subject: {subject or '(connection note)'}\n"
            f"  Body: {body[:150]}..."
        )
        status = LinkedInOutreachStatus.SKIPPED
        error_msg = None
    elif li_automation:
        if li_type == "connection":
            success, error_msg = li_automation.send_connection_request(
                linkedin_url=ceo_linkedin, note=body
            )
        else:
            success, error_msg = li_automation.send_inmail(
                linkedin_url=ceo_linkedin, subject=subject or "", body=body
            )
        status = LinkedInOutreachStatus.SENT if success else LinkedInOutreachStatus.FAILED
        if "Daily limit" in (error_msg or ""):
            status = LinkedInOutreachStatus.DAILY_LIMIT
    else:
        status = LinkedInOutreachStatus.SKIPPED
        error_msg = "No LinkedIn automation initialized"

    log_entry = LinkedInOutreach(
        company_domain=org_domain,
        company_name=org_name,
        contact_name=ceo_name,
        contact_linkedin=ceo_linkedin,
        job_title_hiring=job_title,
        outreach_type=outreach_type,
        message_subject=subject,
        message_body=body[:2000],
        status=status,
        error_message=error_msg if status == LinkedInOutreachStatus.FAILED else None,
        sent_at=datetime.now(timezone.utc) if status == LinkedInOutreachStatus.SENT else None,
    )
    session.add(log_entry)
    session.commit()


def _handle_email_outreach(
    *,
    settings: Settings,
    session,
    ceo_name: str,
    ceo_email: str | None,
    ceo_linkedin: str,
    org_name: str,
    org_domain: str,
    job_title: str,
    logger: logging.Logger,
) -> None:
    """Generate and send email outreach via SMTP (requires Hunter.io email)."""
    from engine.outreach.smtp_sender import send_email

    if not settings.openai_api_key:
        subject = f"Re: your {job_title} hire"
        body = (
            f"Hi {ceo_name.split()[0] if ceo_name else 'there'},\n\n"
            f"Noticed {org_name} is hiring a {job_title} — exciting growth signal.\n\n"
            f"Would love to share some paid acquisition strategies that "
            f"could complement your new hire's efforts.\n\n"
            f"Open to a quick call this week?\n\nBest,\nJoel"
        )
    else:
        subject, body = generate_outreach_email(
            settings=settings,
            ceo_name=ceo_name,
            company_name=org_name,
            job_title_hiring=job_title,
            company_domain=org_domain,
        )

    if settings.dry_run:
        status = EmailStatus.SKIPPED
        logger.info(
            f"[DRY RUN] Email → {ceo_email or '(no email)'} | "
            f"{ceo_name} @ {org_name}\n"
            f"  Subject: {subject}\n"
            f"  Body: {body[:150]}..."
        )
    elif not ceo_email:
        status = EmailStatus.SKIPPED
        logger.info(
            f"No email found for {ceo_name} @ {org_name} — skipping email "
            f"(LinkedIn: {ceo_linkedin})"
        )
    else:
        success = send_email(
            settings=settings,
            to_email=ceo_email,
            to_name=ceo_name,
            subject=subject,
            body=body,
        )
        status = EmailStatus.SENT if success else EmailStatus.FAILED

    log_entry = EmailLog(
        company_domain=org_domain,
        company_name=org_name,
        contact_name=ceo_name,
        contact_email=ceo_email,
        contact_linkedin=ceo_linkedin,
        job_title_hiring=job_title,
        email_subject=subject,
        email_body_preview=body[:500],
        status=status,
        sent_at=datetime.now(timezone.utc) if status == EmailStatus.SENT else None,
    )
    session.add(log_entry)
    session.commit()


RATE_LIMIT_DELAY = 0.15


def check_sumble(settings: Settings) -> None:
    """Verify the Sumble API connection and print account status."""
    import json as _json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)

    logger.info("Checking Sumble API connection...")
    sumble = SumbleClient(settings)
    result = sumble.check_account()

    if result is None:
        logger.error("Sumble API check FAILED. See errors above.")
        sys.exit(1)

    logger.info("Sumble API check PASSED ✓")
    logger.info(f"  Credits remaining: {result.get('credits_remaining', '?')}")
    logger.info(f"  Jobs returned: {len(result.get('jobs', []))}")
    print(_json.dumps(result, indent=2, default=str))


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Job Posting Growth Engine")
    parser.add_argument("--dry-run", action="store_true", help="Log but don't send")
    parser.add_argument("--check", action="store_true", help="Verify Sumble API connection")
    parser.add_argument("--query", type=str, help="Job title query (default: from .env)")
    parser.add_argument("--limit", type=int, help="Max outreach per run (default: from .env)")
    parser.add_argument(
        "--csv", type=str, metavar="FILE",
        help="Import jobs from CSV file (bypasses Sumble Jobs API)",
    )
    parser.add_argument(
        "--csv-contacts", type=str, metavar="FILE",
        help="Import contacts from CSV file (bypasses Sumble People API)",
    )
    parser.add_argument(
        "--channel",
        choices=["email", "linkedin", "both"],
        help="Outreach channel (default: from .env)",
    )
    parser.add_argument(
        "--linkedin-type",
        choices=["inmail", "connection"],
        help="LinkedIn message type (default: from .env)",
    )
    args = parser.parse_args()

    settings = Settings()

    if args.check:
        check_sumble(settings)
        return

    if args.dry_run:
        settings.dry_run = True
    if args.query:
        settings.job_query = args.query
    if args.limit:
        settings.max_emails_per_run = args.limit
    if args.channel:
        settings.outreach_channel = args.channel
    if args.linkedin_type:
        settings.linkedin_outreach_type = args.linkedin_type

    run(settings, csv_jobs=args.csv, csv_contacts=args.csv_contacts)


if __name__ == "__main__":
    main()
