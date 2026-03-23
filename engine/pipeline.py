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
try:
    from engine.ai.followup_writer import generate_followup_email
except ImportError:
    generate_followup_email = None  # Not yet implemented
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
    FollowUpLog,
    FollowUpStatus,
    JobPosting,
    LinkedInOutreach,
    LinkedInOutreachStatus,
    OutreachType,
    RunLog,
)

LOG_PREFIX = "[GrowthEngine]"


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
    stats = {
        "new_jobs": 0,
        "processed": 0,
        "emails_sent": 0,
        "emails_skipped": 0,
        "linkedin_sent": 0,
        "linkedin_skipped": 0,
        "failed": 0,
    }
    contacted_companies: list[str] = []

    # Create run log entry
    run_log = RunLog(
        channel=channel,
        source=source,
        query=settings.job_query,
        dry_run=str(settings.dry_run).lower(),
    )
    session.add(run_log)
    session.commit()

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

    if use_email and settings.loops_api_key and not settings.loops_mailing_list_id and not settings.dry_run:
        logger.error(
            "LOOPS_MAILING_LIST_ID not set — Loop automation won't trigger. "
            "Set it from Loops → Audience → Lists → your list → Settings."
        )
        return stats

    if settings.hunter_api_key:
        hunter = HunterClient(settings)
        logger.info("Hunter.io enabled (email enrichment + domain discovery)")
    elif use_email:
        logger.warning("Email channel selected but HUNTER_API_KEY not set — emails won't be sent")

    # LinkedIn automation (lazy-init only if needed)
    li_automation = None

    if use_linkedin and not settings.dry_run:
        from engine.outreach.linkedin_sender import LinkedInAutomation
        li_automation = LinkedInAutomation(settings)

    # Adzuna client (lazy-init only if configured)
    adzuna = None
    if settings.adzuna_app_id and settings.adzuna_api_key:
        from engine.clients.adzuna import AdzunaClient
        adzuna = AdzunaClient(settings)
        logger.info("Adzuna job search enabled (fallback/supplement to Sumble)")

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

            jobs = []
            if sumble:
                jobs = sumble.find_jobs(
                    query=settings.job_query,
                    technologies=technologies,
                    countries=countries,
                    limit=settings.max_emails_per_run * 3,
                    since=since,
                )

            # Always supplement with Adzuna if configured (Sumble inventory is limited)
            if adzuna:
                needed = settings.max_emails_per_run * 3 - len(jobs)
                logger.info(
                    f"Sumble returned {len(jobs)} jobs — supplementing with Adzuna"
                )
                adzuna_queries = [
                    "head of growth",
                    "performance marketing manager",
                    "growth marketing",
                    "paid media manager",
                    "demand generation",
                    "digital marketing director",
                ]
                seen_ids = {j.get("id") for j in jobs}
                for q in adzuna_queries:
                    if len(jobs) >= settings.max_emails_per_run * 3:
                        break
                    adzuna_jobs = adzuna.find_jobs(
                        query=q,
                        country=(countries[0].lower() if countries else "us"),
                        limit=min(needed, 50),
                    )
                    for aj in adzuna_jobs:
                        if aj["id"] not in seen_ids:
                            seen_ids.add(aj["id"])
                            jobs.append(aj)
                logger.info(f"Total jobs after Adzuna supplement: {len(jobs)}")

        for job in jobs:
            if stats["processed"] >= settings.max_emails_per_run:
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

            # ── Step 1b: Resolve missing domain via Hunter ─────────────
            if not org_domain and org_name and hunter:
                org_domain = hunter.find_domain(org_name)
                if org_domain:
                    logger.info(f"Resolved domain for {org_name} → {org_domain}")
                time.sleep(0.1)

            # ── Step 2: Deduplicate by job ID ────────────────────────
            if session.query(JobPosting).filter_by(sumble_job_id=job_id).first():
                logger.debug(f"Already seen job {job_id} @ {org_name}")
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

            # ── Step 5: Find contact (marketing leader → CEO) ────────
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
                ceo = sumble.find_contact(
                    organization_domain=org_domain,
                    organization_id=org_id,
                )
            else:
                logger.info(f"No contact for {org_name} — provide via --csv-contacts")
                ceo = None

            if not ceo:
                logger.info(f"No contact found for {org_name} ({org_domain}) — skipping")
                stats["failed"] += 1
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
                li_ok = _handle_linkedin_outreach(
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
                if li_ok:
                    stats["linkedin_sent"] += 1
                else:
                    stats["linkedin_skipped"] += 1

            # ── Step 9: Email outreach (if channel includes email) ───
            if use_email:
                email_ok = _handle_email_outreach(
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
                if email_ok:
                    stats["emails_sent"] += 1
                else:
                    stats["emails_skipped"] += 1

            stats["processed"] += 1
            contacted_companies.append(org_name)

            # Rate limit courtesy
            time.sleep(RATE_LIMIT_DELAY)

    except Exception as exc:
        logger.exception(f"{LOG_PREFIX} Pipeline error: {exc}")
    finally:
        if li_automation:
            li_automation.close()
        session.close()

    total_sent = stats["emails_sent"] + stats["linkedin_sent"]

    logger.info("=" * 60)
    logger.info(
        f"{LOG_PREFIX} Complete — "
        f"new_jobs={stats['new_jobs']} processed={stats['processed']} "
        f"emails_sent={stats['emails_sent']} linkedin_sent={stats['linkedin_sent']} "
        f"failed={stats['failed']}"
    )
    logger.info("=" * 60)

    # ── Slack summary ────────────────────────────────────────────────
    post_run_summary(
        webhook_url=settings.effective_slack_webhook,
        sent=total_sent,
        skipped=stats["emails_skipped"] + stats["linkedin_skipped"],
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
) -> bool:
    """Generate and send LinkedIn outreach. Returns True if sent."""

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
    return status == LinkedInOutreachStatus.SENT


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
) -> bool:
    """Generate and send email outreach. Returns True if sent."""

    if not settings.openai_api_key:
        subject = f"Re: your {job_title} hire"
        body = (
            f"Hi {ceo_name.split()[0] if ceo_name else 'there'},\n\n"
            f"Noticed {org_name} is hiring a {job_title} — exciting growth signal.\n\n"
            f"Would love to share some paid acquisition strategies that "
            f"could complement your new hire's efforts.\n\n"
            f"Open to a quick call this week?\n\nBest,\n{settings.sender_name or 'Best'}"
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
        # Try Smartlead first, then Loops, fall back to SMTP
        if settings.smartlead_api_key:
            from engine.outreach.smartlead_sender import send_email as smartlead_send

            success = smartlead_send(
                settings=settings,
                to_email=ceo_email,
                to_name=ceo_name,
                subject=subject,
                body=body,
                company_name=org_name,
                job_title=job_title,
            )
        elif settings.loops_api_key:
            from engine.outreach.loops_sender import send_email as loops_send

            success = loops_send(
                settings=settings,
                to_email=ceo_email,
                to_name=ceo_name,
                subject=subject,
                body=body,
                company_name=org_name,
                job_title=job_title,
            )
        else:
            from engine.outreach.smtp_sender import send_email as smtp_send

            success = smtp_send(
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
    return status == EmailStatus.SENT


RATE_LIMIT_DELAY = 0.15


# ------------------------------------------------------------------
# Follow-up pipeline
# ------------------------------------------------------------------


def run_followups(settings: Settings) -> dict[str, int]:
    """Enrich contacts with SpyFu PPC/SEO data for the Loop's follow-up step.

    The "Cold Job Posting Outreach" Loop has a built-in wait step (3-5 days)
    followed by a second email. This function upserts followupBody,
    followupSubject, monthlyAdSpend, estimatedSavings, and 18+ SpyFu data
    points to each contact so the template variables render correctly.

    For leads without SpyFu data, a generic follow-up is generated instead.

    Run this daily so contacts are enriched before the wait step fires.
    """
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

    logger.info("=" * 60)
    logger.info(f"{LOG_PREFIX} Follow-up enrichment starting")
    logger.info(
        f"  enrich_after_days={settings.spyfu_enrich_after_days}  "
        f"dry_run={settings.dry_run}  max={settings.max_emails_per_run}"
    )
    logger.info("=" * 60)

    SessionFactory = init_db(settings.database_path)
    session = SessionFactory()

    stats = {"eligible": 0, "enriched": 0, "sent": 0, "skipped": 0, "failed": 0}

    # Create run log
    run_log = RunLog(
        channel="followup",
        source="SpyFu",
        query=f"followup (enrich_after={settings.spyfu_enrich_after_days}d)",
        dry_run=str(settings.dry_run).lower(),
    )
    session.add(run_log)
    session.commit()

    # Init SpyFu client (optional — generic follow-ups work without it)
    spyfu = None
    if settings.spyfu_api_id and settings.spyfu_secret_key:
        from engine.clients.spyfu import SpyFuClient
        spyfu = SpyFuClient(settings)
        logger.info("SpyFu enrichment enabled")
    else:
        logger.info("No SPYFU_API_ID/SECRET_KEY — will use generic follow-ups for all leads")

    try:
        from datetime import timedelta
        from engine.ai.followup_writer import generate_generic_followup

        cutoff = datetime.now(timezone.utc) - timedelta(
            days=settings.spyfu_enrich_after_days
        )

        eligible_emails = (
            session.query(EmailLog)
            .filter(
                EmailLog.status == EmailStatus.SENT,
                EmailLog.sent_at <= cutoff,
                EmailLog.contact_email.isnot(None),
                EmailLog.company_domain.isnot(None),
            )
            .all()
        )

        # Filter out already enriched
        already_followed = {
            row.email_log_id
            for row in session.query(FollowUpLog.email_log_id).all()
        }
        eligible_emails = [
            e for e in eligible_emails if e.id not in already_followed
        ]

        stats["eligible"] = len(eligible_emails)
        logger.info(f"Found {len(eligible_emails)} leads to enrich for follow-up")

        for email_log in eligible_emails:
            if stats["sent"] + stats["skipped"] >= settings.max_emails_per_run:
                logger.info("Max per run reached — stopping.")
                break

            domain = email_log.company_domain
            company = email_log.company_name
            contact = email_log.contact_name
            contact_email = email_log.contact_email
            job_title = email_log.job_title_hiring

            logger.info(f"Enriching: {contact} @ {company} ({domain})")

            # Try SpyFu if available
            ad_spend = None
            monthly_spend = 0.0
            savings_low = 0.0
            savings_high = 0.0

            if spyfu and domain:
                ad_spend = spyfu.enrich_domain(domain)

            if ad_spend and ad_spend.get("estimated_monthly_spend", 0) >= 100:
                # Has real ad spend data — generate data-driven follow-up
                stats["enriched"] += 1
                monthly_spend = ad_spend["estimated_monthly_spend"]
                savings_low = monthly_spend * 0.15
                savings_high = monthly_spend * 0.25

                subject, body = generate_followup_email(
                    settings=settings,
                    ceo_name=contact,
                    company_name=company,
                    job_title_hiring=job_title,
                    ad_spend=ad_spend,
                    company_domain=domain,
                )
            else:
                # No ad spend data — generate generic follow-up
                subject, body = generate_generic_followup(
                    settings=settings,
                    ceo_name=contact,
                    company_name=company,
                    job_title_hiring=job_title,
                    company_domain=domain,
                )

            # Upsert to Loops contact properties (all SpyFu enrichment data)
            if settings.dry_run:
                spend_info = f"${monthly_spend:,.0f}/mo" if monthly_spend else "no data"
                logger.info(
                    f"[DRY RUN] Enrich → {contact_email} | {contact} @ {company}\n"
                    f"  Ad spend: {spend_info}\n"
                    f"  Subject: {subject}\n"
                    f"  Body: {body[:150]}..."
                )
                fu_status = FollowUpStatus.SKIPPED
            elif settings.loops_api_key:
                from engine.outreach.loops_sender import enrich_for_followup

                success = enrich_for_followup(
                    settings=settings,
                    to_email=contact_email,
                    to_name=contact,
                    subject=subject,
                    body=body,
                    company_name=company,
                    monthly_spend=monthly_spend,
                    savings_low=savings_low,
                    savings_high=savings_high,
                    spyfu_data=ad_spend,
                )
                fu_status = FollowUpStatus.SENT if success else FollowUpStatus.FAILED
            else:
                logger.warning("LOOPS_API_KEY not set — cannot enrich contacts")
                fu_status = FollowUpStatus.SKIPPED

            # Log
            followup = FollowUpLog(
                email_log_id=email_log.id,
                company_domain=domain,
                company_name=company,
                contact_name=contact,
                contact_email=contact_email,
                estimated_monthly_spend=monthly_spend if monthly_spend else None,
                estimated_annual_spend=(
                    ad_spend.get("annual_spend") if ad_spend else None
                ),
                ppc_keywords=ad_spend.get("ppc_keywords") if ad_spend else None,
                organic_keywords=ad_spend.get("organic_keywords") if ad_spend else None,
                domain_strength=ad_spend.get("domain_strength") if ad_spend else None,
                top_competitor=ad_spend.get("top_competitor") if ad_spend else None,
                total_ads=ad_spend.get("total_ads") if ad_spend else None,
                email_subject=subject,
                email_body_preview=body[:500],
                status=fu_status,
                sent_at=(
                    datetime.now(timezone.utc)
                    if fu_status == FollowUpStatus.SENT
                    else None
                ),
            )
            session.add(followup)
            session.commit()

            if fu_status == FollowUpStatus.SENT:
                stats["sent"] += 1
            elif fu_status == FollowUpStatus.FAILED:
                stats["failed"] += 1
            else:
                stats["skipped"] += 1

            time.sleep(RATE_LIMIT_DELAY)

    except Exception as exc:
        logger.exception(f"{LOG_PREFIX} Follow-up enrichment error: {exc}")
    finally:
        run_log.followups_sent = stats["sent"]
        run_log.followups_skipped = stats["skipped"]
        run_log.total_processed = stats["eligible"]
        run_log.total_failed = stats["failed"]
        run_log.finished_at = datetime.now(timezone.utc)
        session.commit()
        session.close()

    logger.info("=" * 60)
    logger.info(
        f"{LOG_PREFIX} Enrichment complete — "
        f"eligible={stats['eligible']} enriched={stats['enriched']} "
        f"upserted={stats['sent']} skipped={stats['skipped']} failed={stats['failed']}"
    )
    logger.info("=" * 60)

    post_run_summary(
        webhook_url=settings.effective_slack_webhook,
        sent=stats["sent"],
        skipped=stats["skipped"],
        failed=stats["failed"],
        sample_companies=[],
    )

    return stats


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


def run_enrichment(
    settings: Settings,
    *,
    output_path: str | None = None,
    export_format: str | None = None,
) -> dict[str, int]:
    """Enrich all eligible leads with SpyFu + BuiltWith + Firecrawl + AI.

    Reads sent email logs from the DB, enriches each lead with all data
    sources, and optionally exports to Instantly CSV format.

    Args:
        settings:       App settings.
        output_path:    Optional CSV output path (default: auto-generated).
        export_format:  "instantly" to export CSV, or None to skip export.

    Returns:
        Stats dict with eligible, enriched, exported, failed counts.
    """
    from engine.enrichment import enrich_lead

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

    logger.info("=" * 60)
    logger.info(f"{LOG_PREFIX} Multi-source enrichment starting")
    logger.info(
        f"  dry_run={settings.dry_run}  max={settings.max_emails_per_run}  "
        f"export={export_format or 'none'}"
    )
    logger.info("=" * 60)

    SessionFactory = init_db(settings.database_path)
    session = SessionFactory()
    stats = {"eligible": 0, "enriched": 0, "exported": 0, "failed": 0, "skipped": 0}
    enriched_leads: list[dict] = []

    # Create run log
    run_log = RunLog(
        channel="enrichment",
        source="SpyFu+BuiltWith+Firecrawl",
        query=f"enrich (export={export_format or 'none'})",
        dry_run=str(settings.dry_run).lower(),
    )
    session.add(run_log)
    session.commit()

    try:
        # Find all sent emails that haven't been enriched yet
        already_enriched = {
            row.email_log_id
            for row in session.query(FollowUpLog.email_log_id).all()
        }

        eligible_emails = (
            session.query(EmailLog)
            .filter(
                EmailLog.status == EmailStatus.SENT,
                EmailLog.contact_email.isnot(None),
                EmailLog.company_domain.isnot(None),
            )
            .all()
        )
        eligible_emails = [
            e for e in eligible_emails if e.id not in already_enriched
        ]

        stats["eligible"] = len(eligible_emails)
        logger.info(f"Found {len(eligible_emails)} leads to enrich")

        for email_log in eligible_emails:
            if stats["enriched"] + stats["skipped"] >= settings.max_emails_per_run:
                logger.info("Max per run reached — stopping.")
                break

            domain = email_log.company_domain
            company = email_log.company_name
            contact = email_log.contact_name
            contact_email = email_log.contact_email

            logger.info(f"Enriching: {contact} @ {company} ({domain})")

            if settings.dry_run:
                logger.info(f"  [DRY RUN] Would enrich {domain} with all sources")
                stats["skipped"] += 1
                continue

            try:
                lead_data = enrich_lead(
                    settings=settings,
                    domain=domain,
                    company_name=company,
                    contact_name=contact,
                    job_title_hiring=email_log.job_title_hiring,
                )
                lead_data["contact_email"] = contact_email
                lead_data["contact_title"] = email_log.job_title_hiring

                enriched_leads.append(lead_data)
                stats["enriched"] += 1

                # Log to DB
                followup = FollowUpLog(
                    email_log_id=email_log.id,
                    company_domain=domain,
                    company_name=company,
                    contact_name=contact,
                    contact_email=contact_email,
                    estimated_monthly_spend=lead_data.get("spyfu_monthly_spend"),
                    estimated_annual_spend=lead_data.get("spyfu_annual_spend"),
                    ppc_keywords=lead_data.get("spyfu_ppc_keywords"),
                    organic_keywords=lead_data.get("spyfu_organic_keywords"),
                    domain_strength=lead_data.get("spyfu_domain_strength"),
                    top_competitor=lead_data.get("spyfu_top_competitor"),
                    total_ads=lead_data.get("spyfu_total_ads"),
                    status=FollowUpStatus.ENRICHED,
                )
                session.add(followup)
                session.commit()

                logger.info(
                    f"  Enriched: spend=${lead_data.get('spyfu_monthly_spend', 0):,.0f}/mo, "
                    f"pixels={lead_data.get('builtwith_pixel_count', 0)}, "
                    f"headline=\"{lead_data.get('firecrawl_headline', '')[:40]}\""
                )

            except Exception as exc:
                logger.error(f"  Enrichment failed for {domain}: {exc}")
                stats["failed"] += 1

            time.sleep(1)  # overall pacing between leads

    except Exception as exc:
        logger.exception(f"{LOG_PREFIX} Enrichment error: {exc}")
    finally:
        run_log.total_processed = stats["enriched"]
        run_log.total_failed = stats["failed"]
        run_log.finished_at = datetime.now(timezone.utc)
        session.commit()
        session.close()

    # Export enriched leads
    if export_format == "loops" and enriched_leads:
        from engine.outreach.loops_sender import add_contact

        pushed = 0
        for lead in enriched_leads:
            email = lead.get("contact_email", "")
            if not email:
                continue
            full_name = lead.get("contact_name", "")
            parts = full_name.split() if full_name else []
            first_name = parts[0] if parts else ""
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

            # These fields are used in email subject lines. Loops won't
            # send emails to contacts missing subject-line merge tags,
            # so skip leads that don't have real data for them.
            SUBJECT_LINE_FIELDS = {
                "spyfu_waste_keywords",
                "spyfu_top_ad_days",
                "spyfu_gap_keyword",
                "spyfu_organic_click_value",
                "builtwith_tech_stack",
            }
            job_title = lead.get("job_title_hiring", "")
            if not job_title:
                logger.warning("Skipping %s: missing job_title_hiring", email)
                continue
            missing = [f for f in SUBJECT_LINE_FIELDS if not lead.get(f)]
            if missing:
                logger.warning("Skipping %s: missing subject-line fields %s", email, missing)
                continue

            # Map all enrichment fields to Loops contact properties
            # Format monetary/numeric values for display in email templates
            props: dict[str, str] = {}

            # Fields that should be formatted as $X,XXX
            MONEY_FIELDS = {
                "spyfu_monthly_spend", "spyfu_annual_spend",
                "spyfu_competitor_spend", "spyfu_organic_click_value",
                "spyfu_gap_keyword_cpc",
            }
            # Fields that should be formatted with commas (large integers)
            COMMA_FIELDS = {
                "spyfu_ppc_keywords", "spyfu_organic_keywords",
                "spyfu_paid_clicks", "spyfu_organic_clicks",
                "spyfu_shared_keywords",
            }

            for key, val in lead.items():
                if key.startswith(("spyfu_", "builtwith_", "firecrawl_", "ai_", "settings_")):
                    if isinstance(val, list):
                        props[key] = ", ".join(str(v) for v in val)
                    elif key in MONEY_FIELDS and isinstance(val, (int, float)) and val:
                        props[key] = f"${val:,.0f}" if val >= 1 else f"${val:.2f}"
                    elif key in COMMA_FIELDS and isinstance(val, (int, float)) and val:
                        props[key] = f"{int(val):,}"
                    elif val:
                        props[key] = str(val)

            # Computed field: estimated savings (20% of monthly spend)
            monthly = lead.get("spyfu_monthly_spend", 0)
            if monthly and isinstance(monthly, (int, float)) and monthly > 0:
                props["spyfu_estimated_savings"] = f"${monthly * 0.20:,.0f}"

            props["jobTitleHiring"] = lead.get("job_title_hiring", "")

            # Apply fallback defaults for body-only merge tags.
            # Subject-line fields are guaranteed present (filtered above).
            BODY_FALLBACKS = {
                "spyfu_monthly_spend": "real money",
                "spyfu_annual_spend": "your annual spend",
                "spyfu_ppc_keywords": "hundreds of",
                "spyfu_organic_keywords": "many",
                "spyfu_paid_clicks": "thousands",
                "spyfu_organic_clicks": "thousands",
                "spyfu_domain_strength": "competitive",
                "spyfu_top_competitor": "your closest competitor",
                "spyfu_competitor_spend": "more than you",
                "spyfu_shared_keywords": "hundreds of",
                "spyfu_gap_keyword_cpc": "premium",
                "spyfu_top_headline": "...",
                "spyfu_total_ads": "a handful of",
                "spyfu_seo_top10": "many",
                "builtwith_installed_pixels": "some",
                "builtwith_missing_pixels": "several platforms",
                "firecrawl_headline": "something generic",
                "settings_calendly_url": "https://calendly.com/synter/15min",
            }
            for key, fallback in BODY_FALLBACKS.items():
                if not props.get(key):
                    props[key] = fallback

            ok = add_contact(
                settings=settings,
                email=email,
                first_name=first_name,
                last_name=last_name,
                company=lead.get("company_name", ""),
                source="growth-engine-enrichment",
                custom_properties=props,
            )
            if ok:
                pushed += 1

        stats["exported"] = pushed
        logger.info(f"Pushed {pushed} enriched leads to Loops.so")

        # Enroll exported contacts in the drip sequence
        from engine.drip.scheduler import enroll_contact

        drip_session = init_db(settings.db_path)()
        enrolled = 0
        try:
            for lead in enriched_leads:
                lead_email = lead.get("contact_email", "")
                if not lead_email:
                    continue
                full = lead.get("contact_name", "")
                fn = full.split()[0] if full else ""
                state = enroll_contact(
                    session=drip_session,
                    email=lead_email,
                    first_name=fn,
                    company=lead.get("company_name", ""),
                    enrichment_data=lead,
                )
                if state:
                    enrolled += 1
            drip_session.commit()
        finally:
            drip_session.close()
        logger.info(f"Drip: enrolled {enrolled} new contacts")

    elif export_format == "instantly" and enriched_leads:
        from engine.export.instantly_csv import export_csv

        csv_path = export_csv(enriched_leads, output_path=output_path)
        stats["exported"] = len(enriched_leads)
        logger.info(f"Exported {len(enriched_leads)} leads to {csv_path}")

    logger.info("=" * 60)
    logger.info(
        f"{LOG_PREFIX} Enrichment complete — "
        f"eligible={stats['eligible']} enriched={stats['enriched']} "
        f"exported={stats['exported']} failed={stats['failed']}"
    )
    logger.info("=" * 60)

    return stats


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Job Posting Growth Engine")
    parser.add_argument("--dry-run", action="store_true", help="Log but don't send")
    parser.add_argument("--check", action="store_true", help="Verify Sumble API connection")
    parser.add_argument(
        "--followups", action="store_true",
        help="Run follow-up pipeline (SpyFu enrichment + Day 3-5 emails)",
    )
    parser.add_argument(
        "--enrich", action="store_true",
        help="Run multi-source enrichment (SpyFu + BuiltWith + Firecrawl + AI)",
    )
    parser.add_argument(
        "--export",
        choices=["loops", "instantly"],
        metavar="FORMAT",
        help="Export enriched leads (loops = push to Loops.so, instantly = CSV)",
    )
    parser.add_argument(
        "--output", type=str, metavar="FILE",
        help="Output file path for export (default: auto-generated in data/)",
    )
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
    parser.add_argument(
        "--drip", action="store_true",
        help="Run drip scheduler — sends next due email for each active contact",
    )
    # X Growth Engine flags
    parser.add_argument(
        "--x-post", action="store_true",
        help="Post next scheduled item from X content calendar",
    )
    parser.add_argument(
        "--x-scan", action="store_true",
        help="Scan X for engagement opportunities",
    )
    parser.add_argument(
        "--x-list", action="store_true",
        help="List all posts in X content calendar with status",
    )
    parser.add_argument(
        "--x-engage", type=int, metavar="N",
        help="Engage with scan candidate at index N",
    )
    parser.add_argument(
        "--x-comment", type=str,
        help="Custom comment for X engagement",
    )
    parser.add_argument(
        "--x-mcp-replies", action="store_true",
        help="Scan for Claude+Facebook Ads+MCP tweets and auto-reply",
    )
    parser.add_argument(
        "--li-crosspost", action="store_true",
        help="Cross-post next eligible X post to LinkedIn",
    )
    parser.add_argument(
        "--li-crosspost-all", action="store_true",
        help="Cross-post all pending X posts to LinkedIn",
    )
    # Listicle placement commands
    parser.add_argument(
        "--listicle-discover", action="store_true",
        help="Discover listicle articles for Synter placement",
    )
    parser.add_argument(
        "--listicle-enrich", action="store_true",
        help="Find editor contacts for discovered listicle targets",
    )
    parser.add_argument(
        "--listicle-outreach", action="store_true",
        help="Send outreach emails to listicle editors",
    )
    parser.add_argument(
        "--listicle-status", action="store_true",
        help="Show listicle outreach pipeline status",
    )
    parser.add_argument(
        "--listicle-list", action="store_true",
        help="List all listicle targets",
    )
    # Podcast placement commands
    parser.add_argument(
        "--podcast-discover", action="store_true",
        help="Discover podcasts for guest appearance outreach",
    )
    parser.add_argument(
        "--podcast-enrich", action="store_true",
        help="Find host contacts for discovered podcasts",
    )
    parser.add_argument(
        "--podcast-outreach", action="store_true",
        help="Send guest pitch emails to podcast hosts",
    )
    parser.add_argument(
        "--podcast-list", action="store_true",
        help="List all podcast targets",
    )
    parser.add_argument(
        "--listicle-followups", action="store_true",
        help="Send follow-up emails to targets that haven't responded (3-day cadence)",
    )

    args = parser.parse_args()

    settings = Settings()

    if args.check:
        check_sumble(settings)
        return

    if args.dry_run:
        settings.dry_run = True

    if args.limit:
        settings.max_emails_per_run = args.limit

    # --- X Growth Engine commands ---
    if args.x_list:
        from engine.x.scheduled_post import load_calendar, load_posted_log, list_posts
        list_posts(load_calendar(), load_posted_log())
        return

    if args.x_post:
        from engine.x.scheduled_post import (
            load_calendar, load_posted_log, save_posted_log,
            get_next_post, get_oauth_session, post_tweet,
        )
        import json as _json
        calendar = load_calendar()
        posted = load_posted_log()
        post_id, post = get_next_post(calendar, posted)
        if not post:
            print(_json.dumps({"success": False, "error": "All posts have been sent"}))
            return
        text = post.get("text", "")
        if settings.dry_run:
            print(f"[DRY RUN] {post_id}: {post.get('day')} {post.get('time')} ({post.get('type')})")
            print(f"  {text}")
            print(f"  chars: {len(text)}")
            return
        if len(text) > 280:
            print(_json.dumps({"success": False, "error": f"Exceeds 280 chars ({len(text)})"}))
            return
        oauth = get_oauth_session()
        result = post_tweet(oauth, text)
        tid = result.get("data", {}).get("id", "")
        posted.add(post_id)
        save_posted_log(posted)
        print(_json.dumps({
            "success": True, "post_id": post_id, "tweet_id": tid,
            "url": f"https://x.com/JSHorwitz/status/{tid}",
            "day": post.get("day"), "type": post.get("type"),
        }, indent=2))
        return

    if args.x_scan:
        from engine.x.engagement_scanner import run_scan, save_candidates
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        candidates = run_scan()
        scan_data = {
            "scanned_at": _dt.now(_tz.utc).isoformat(),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
        if not settings.dry_run:
            save_candidates(scan_data)
        print(_json.dumps({
            "success": True, "dry_run": settings.dry_run,
            "candidate_count": len(candidates),
            "top_5": [
                {"url": c["url"], "likes": c["likes"], "author": f"@{c['author_username']}", "score": c["score"]}
                for c in candidates[:5]
            ],
        }, indent=2))
        return

    if args.x_engage is not None:
        from engine.x.engagement_scanner import load_candidates, engage_candidate
        import json as _json
        data = load_candidates()
        candidates = data.get("candidates", [])
        if args.x_engage >= len(candidates):
            print(_json.dumps({"success": False, "error": f"index {args.x_engage} out of range (have {len(candidates)})"}))
            return
        result = engage_candidate(candidates[args.x_engage], args.x_comment)
        print(_json.dumps(result, indent=2))
        return

    if args.x_mcp_replies:
        from engine.x.mcp_reply_scanner import run_scan_and_reply
        import json as _json
        result = run_scan_and_reply(max_replies=5, dry_run=settings.dry_run)
        print(_json.dumps(result, indent=2))
        return

    if args.li_crosspost or args.li_crosspost_all:
        from engine.x.linkedin_crosspost import (
            load_linkedin_posted, save_linkedin_posted, adapt_for_linkedin,
            post_to_linkedin, get_next_crosspost, CROSSPOST_TYPES,
        )
        from engine.x.scheduled_post import load_calendar, load_posted_log, _get_week_keys
        import json as _json

        calendar = load_calendar()
        x_posted = load_posted_log()
        li_posted = load_linkedin_posted()
        posts_to_send = []

        if args.li_crosspost_all:
            for week_key in _get_week_keys(calendar):
                for i, post in enumerate(calendar.get(week_key, [])):
                    post_id = f"{week_key}_{i}"
                    if post.get("type", "") in CROSSPOST_TYPES and post_id in x_posted and post_id not in li_posted:
                        posts_to_send.append((post_id, post))
        else:
            post_id, post = get_next_crosspost(calendar, x_posted, li_posted)
            if post:
                posts_to_send.append((post_id, post))

        if not posts_to_send:
            print(_json.dumps({"success": False, "error": "No pending cross-posts"}))
            return

        if settings.dry_run:
            for post_id, post in posts_to_send:
                adapted = adapt_for_linkedin(post)
                print(f"[DRY RUN] {post_id}: {post.get('day')} ({post.get('type')}) → LinkedIn ({len(adapted)} chars)")
            return

        token = settings.linkedin_personal_access_token
        person_urn = settings.linkedin_person_urn
        if not token or not person_urn:
            print(_json.dumps({"success": False, "error": "Set LINKEDIN_PERSONAL_ACCESS_TOKEN and LINKEDIN_PERSON_URN"}))
            return

        results = []
        for post_id, post in posts_to_send:
            adapted = adapt_for_linkedin(post)
            try:
                result = post_to_linkedin(token, person_urn, adapted)
                if result.get("success"):
                    li_posted.add(post_id)
                    save_linkedin_posted(li_posted)
                    results.append({"post_id": post_id, "status": "sent", "linkedin_post_id": result.get("post_id", "")})
                else:
                    results.append({"post_id": post_id, "status": "failed", "error": result.get("error", "")})
            except Exception as e:
                results.append({"post_id": post_id, "status": "failed", "error": str(e)})

        print(_json.dumps({"success": True, "results": results}, indent=2))
        return

    # --- Listicle Placement commands ---
    if args.listicle_discover:
        from engine.listicle.scraper import discover_via_serper, discover_via_google_cse, store_targets, SEARCH_QUERIES
        import json as _json

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()

        serper_key = getattr(settings, "serper_api_key", "")
        google_key = getattr(settings, "google_cse_api_key", "")
        google_cse_id = getattr(settings, "google_cse_id", "")

        targets = []
        if serper_key:
            targets = discover_via_serper(serper_key)
        elif google_key and google_cse_id:
            targets = discover_via_google_cse(google_key, google_cse_id)
        else:
            print(_json.dumps({"success": False, "error": "Set SERPER_API_KEY or GOOGLE_CSE_API_KEY+GOOGLE_CSE_ID"}))
            return

        if settings.dry_run:
            print(_json.dumps({"success": True, "dry_run": True, "count": len(targets), "targets": targets[:10]}, indent=2))
        else:
            stats = store_targets(lsession, targets)
            print(_json.dumps({"success": True, **stats}, indent=2))
        lsession.close()
        return

    if args.listicle_enrich:
        from engine.listicle.enricher import enrich_targets
        import json as _json

        if not settings.hunter_api_key:
            print(_json.dumps({"success": False, "error": "HUNTER_API_KEY not set"}))
            return

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        hunter_client = HunterClient(settings)
        stats = enrich_targets(lsession, hunter_client, dry_run=settings.dry_run, limit=args.limit or 20)
        print(_json.dumps({"success": True, "dry_run": settings.dry_run, **stats}, indent=2))
        lsession.close()
        return

    if args.listicle_outreach:
        from engine.listicle.outreach import send_outreach
        import json as _json

        if not settings.resend_api_key:
            print(_json.dumps({"success": False, "error": "RESEND_API_KEY not set"}))
            return

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        stats = send_outreach(lsession, settings, dry_run=settings.dry_run, limit=args.limit or 10)
        print(_json.dumps({"success": True, "dry_run": settings.dry_run, **stats}, indent=2))
        lsession.close()
        return

    if args.listicle_status:
        from engine.listicle.outreach import show_status

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        show_status(lsession)
        lsession.close()
        return

    if args.listicle_list:
        from engine.listicle.scraper import list_targets
        import json as _json

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        targets = list_targets(lsession)
        for t in targets:
            status_icon = "✅" if t["status"] == "listed" else "📧" if "outreach" in t["status"] else "👤" if t["status"] == "contact_found" else "⬜"
            print(f"  {status_icon} [{t['id']:3d}] DR:{t['domain_rating'] or '?':>3} | {t['domain']:>30} | {t['status']:>15} | {t['title']}")
        print(f"\nTotal: {len(targets)}")
        lsession.close()
        return

    # --- Podcast Placement commands ---
    if args.podcast_discover:
        from engine.listicle.scraper import discover_via_serper, store_targets
        import json as _json

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()

        serper_key = getattr(settings, "serper_api_key", "")
        if not serper_key:
            print(_json.dumps({"success": False, "error": "Set SERPER_API_KEY for discovery"}))
            return

        targets = discover_via_serper(serper_key, target_type="podcast")

        if settings.dry_run:
            print(_json.dumps({"success": True, "dry_run": True, "count": len(targets), "targets": targets[:10]}, indent=2))
        else:
            stats = store_targets(lsession, targets)
            print(_json.dumps({"success": True, **stats}, indent=2))
        lsession.close()
        return

    if args.podcast_enrich:
        from engine.listicle.enricher import enrich_targets
        import json as _json

        if not settings.hunter_api_key:
            print(_json.dumps({"success": False, "error": "HUNTER_API_KEY not set"}))
            return

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        hunter_client = HunterClient(settings)
        stats = enrich_targets(lsession, hunter_client, dry_run=settings.dry_run, limit=args.limit or 20, target_type="podcast")
        print(_json.dumps({"success": True, "dry_run": settings.dry_run, **stats}, indent=2))
        lsession.close()
        return

    if args.podcast_outreach:
        from engine.listicle.outreach import send_outreach
        import json as _json

        if not settings.resend_api_key:
            print(_json.dumps({"success": False, "error": "RESEND_API_KEY not set"}))
            return

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        stats = send_outreach(lsession, settings, dry_run=settings.dry_run, limit=args.limit or 10, target_type="podcast")
        print(_json.dumps({"success": True, "dry_run": settings.dry_run, **stats}, indent=2))
        lsession.close()
        return

    if args.podcast_list:
        from engine.listicle.scraper import list_targets
        import json as _json

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        targets = list_targets(lsession, target_type="podcast")
        for t in targets:
            status_icon = "✅" if t["status"] == "listed" else "📧" if "outreach" in t["status"] else "👤" if t["status"] == "contact_found" else "⬜"
            print(f"  {status_icon} [{t['id']:3d}] 🎙️ {t['domain']:>30} | {t['status']:>15} | {t['title']}")
        print(f"\nTotal: {len(targets)}")
        lsession.close()
        return

    if args.listicle_followups:
        from engine.listicle.outreach import send_followups
        import json as _json

        if not settings.resend_api_key:
            print(_json.dumps({"success": False, "error": "RESEND_API_KEY not set"}))
            return

        SessionFactory = init_db(settings.database_path)
        lsession = SessionFactory()
        stats = send_followups(lsession, settings, dry_run=settings.dry_run, limit=args.limit or 30)
        print(_json.dumps({"success": True, "dry_run": settings.dry_run, **stats}, indent=2))
        lsession.close()
        return

    if args.drip:
        from engine.drip.scheduler import run_drip

        drip_session_factory = init_db(settings.db_path)
        drip_session = drip_session_factory()
        try:
            drip_stats = run_drip(
                session=drip_session,
                settings=settings,
                dry_run=settings.dry_run,
                limit=args.limit or 50,
            )
            logger.info(f"Drip stats: {drip_stats}")
        finally:
            drip_session.close()
        return

    if args.enrich:
        run_enrichment(
            settings,
            output_path=args.output,
            export_format=args.export,
        )
        return

    if args.followups:
        run_followups(settings)
        return

    if args.query:
        settings.job_query = args.query
    if args.channel:
        settings.outreach_channel = args.channel
    if args.linkedin_type:
        settings.linkedin_outreach_type = args.linkedin_type

    run(settings, csv_jobs=args.csv, csv_contacts=args.csv_contacts)


if __name__ == "__main__":
    main()
