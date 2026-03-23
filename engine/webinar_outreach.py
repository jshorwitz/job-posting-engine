"""Webinar Series Outreach Pipeline.

Pulls companies hiring for paid media/growth roles from the job_postings
and contacts tables, generates personalized webinar invite emails via
OpenAI, and sends via Smartlead (cold) or Loops (warm).

Usage:
    python -m engine.webinar_outreach [--channel email|linkedin|both] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from engine.ai.webinar_email_writer import generate_webinar_invite
from engine.config import Settings
from engine.db.database import init_db
from engine.db.models import Contact, JobPosting, EmailLog, EmailStatus
from engine.outreach.smartlead_sender import send_email as smartlead_send
from engine.outreach.loops_sender import send_email as loops_send

logger = logging.getLogger(__name__)
LOG_PREFIX = "[WebinarOutreach]"

# Paid media job title keywords
PAID_MEDIA_KEYWORDS = [
    "paid media", "ppc", "performance market", "growth market",
    "demand gen", "media buy", "digital market", "marketing manager",
    "marketing director", "head of market", "head of growth", "cmo",
    "paid acquisition", "paid social", "sem ",
]

SERIES_URL = "https://syntermedia.ai/lp/growth-machines"


def get_paid_media_contacts(session) -> list[dict]:
    """Get contacts at companies hiring for paid media roles."""
    contacts = session.query(Contact).all()
    jobs = session.query(JobPosting).all()

    # Build set of company domains hiring for paid media
    hiring_domains = set()
    job_by_domain = {}
    for job in jobs:
        title = (job.job_title or "").lower()
        if any(kw in title for kw in PAID_MEDIA_KEYWORDS):
            if job.company_domain:
                hiring_domains.add(job.company_domain.lower())
                job_by_domain[job.company_domain.lower()] = job.job_title

    # Match contacts to hiring companies
    results = []
    for contact in contacts:
        domain = (contact.company_domain or "").lower()
        if domain in hiring_domains and contact.email:
            results.append({
                "name": contact.full_name,
                "email": contact.email,
                "domain": domain,
                "job_title": contact.job_title or "",
                "hiring_for": job_by_domain.get(domain, ""),
            })

    return results


def run(channel: str = "email", dry_run: bool = False, sender: str = "smartlead"):
    """Run the webinar outreach pipeline."""
    settings = Settings()
    db_path = settings.db_path if hasattr(settings, "db_path") else "data/outreach.db"
    Session = init_db(db_path)
    session = Session()

    contacts = get_paid_media_contacts(session)
    logger.info(f"{LOG_PREFIX} Found {len(contacts)} contacts at companies hiring paid media")

    sent = 0
    skipped = 0

    for contact in contacts:
        # Check if already emailed (skip dedup for now — EmailLog schema varies)
        # TODO: add proper dedup once EmailLog schema is confirmed

        # Generate personalized invite
        subject, body = generate_webinar_invite(
            settings=settings,
            contact_name=contact["name"],
            company_name=contact["domain"],
            job_title_hiring=contact["hiring_for"],
            company_domain=contact["domain"],
        )

        if dry_run:
            print(f"\n--- TO: {contact['name']} <{contact['email']}> ---")
            print(f"SUBJECT: {subject}")
            print(f"BODY:\n{body}")
            print(f"HIRING FOR: {contact['hiring_for']}")
            sent += 1
            continue

        # Send via configured channel
        success = False
        if sender == "smartlead":
            success = smartlead_send(
                settings=settings,
                to_email=contact["email"],
                to_name=contact["name"],
                subject=subject,
                body=body,
                company_name=contact["domain"],
                job_title=contact["job_title"],
            )
        elif sender == "loops":
            success = loops_send(
                settings=settings,
                to_email=contact["email"],
                to_name=contact["name"],
                subject=subject,
                body=body,
                company_name=contact["domain"],
                job_title=contact["job_title"],
            )

        if success:
            sent += 1
            logger.info(f"{LOG_PREFIX} Sent to {contact['name']} ({contact['email']})")
        else:
            skipped += 1
            logger.warning(f"{LOG_PREFIX} Failed to send to {contact['email']}")

    logger.info(f"{LOG_PREFIX} Done: {sent} sent, {skipped} skipped")
    return sent, skipped


def main():
    parser = argparse.ArgumentParser(description="Webinar series outreach")
    parser.add_argument("--channel", choices=["email", "linkedin", "both"], default="email")
    parser.add_argument("--sender", choices=["smartlead", "loops"], default="smartlead")
    parser.add_argument("--dry-run", action="store_true", help="Preview emails without sending")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    run(channel=args.channel, dry_run=args.dry_run, sender=args.sender)


if __name__ == "__main__":
    main()
