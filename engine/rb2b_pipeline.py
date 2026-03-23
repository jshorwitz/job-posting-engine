"""RB2B visitor → outreach pipeline.

Polls RB2B for identified website visitors, enriches them with Synter
SimilarWeb + SpyFu + BuiltWith data, generates personalized media plan
emails, and sends via Smartlead/Loops.

Can run standalone or be triggered by webhook.

Usage:
    python -m engine.rb2b_pipeline              # poll RB2B API
    python -m engine.rb2b_pipeline --webhook    # start webhook server
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

from sqlalchemy.orm import Session

from engine.config import Settings
from engine.db.database import get_session
from engine.db.models import EmailLog, EmailStatus, RB2BVisitor
from engine.enrichment import enrich_lead

logger = logging.getLogger(__name__)


def run_rb2b_pipeline(
    settings: Settings,
    session: Session,
    *,
    source: str = "rb2b_poll",
) -> dict[str, int]:
    """Process RB2B visitors: enrich → generate email → send.

    Finds visitors where outreach_sent=False, enriches them,
    generates personalized media plan emails, and sends.
    """
    stats = {"processed": 0, "enriched": 0, "sent": 0, "skipped": 0, "failed": 0}

    # Fetch unprocessed visitors
    visitors = (
        session.query(RB2BVisitor)
        .filter_by(outreach_sent=False)
        .filter(RB2BVisitor.visitor_email.isnot(None))
        .filter(RB2BVisitor.company_domain != "")
        .limit(settings.max_emails_per_run)
        .all()
    )

    if not visitors:
        logger.info("[RB2B] No new visitors to process")
        return stats

    logger.info(f"[RB2B] Processing {len(visitors)} visitors")

    for visitor in visitors:
        stats["processed"] += 1

        # Check if already contacted this domain
        existing = (
            session.query(EmailLog)
            .filter_by(company_domain=visitor.company_domain)
            .filter(EmailLog.status.in_([EmailStatus.SENT, EmailStatus.SKIPPED]))
            .first()
        )
        if existing:
            logger.info(f"[RB2B] Already contacted {visitor.company_domain}, skipping")
            visitor.outreach_sent = True
            session.commit()
            stats["skipped"] += 1
            continue

        # Enrich with all sources including Synter SimilarWeb
        enrichment = enrich_lead(
            settings=settings,
            domain=visitor.company_domain,
            company_name=visitor.company_name,
            contact_name=visitor.visitor_name,
            job_title_hiring=visitor.job_title or "marketing leader",
        )
        stats["enriched"] += 1

        # Store enrichment data
        visitor.enrichment_json = json.dumps(enrichment, default=str)
        session.commit()

        # Generate and send email
        success = _send_rb2b_outreach(
            settings=settings,
            session=session,
            visitor=visitor,
            enrichment=enrichment,
        )

        if success:
            visitor.outreach_sent = True
            session.commit()
            stats["sent"] += 1
        else:
            stats["failed"] += 1

    logger.info(
        f"[RB2B] Pipeline complete: {stats['processed']} processed, "
        f"{stats['sent']} sent, {stats['skipped']} skipped, {stats['failed']} failed"
    )
    return stats


def _send_rb2b_outreach(
    settings: Settings,
    session: Session,
    visitor: RB2BVisitor,
    enrichment: dict,
) -> bool:
    """Generate and send a personalized media plan email to an RB2B visitor."""
    from engine.ai.email_writer import generate_outreach_email

    first_name = visitor.visitor_name.split()[0] if visitor.visitor_name else "there"

    # Build context-enriched email using SimilarWeb data if available
    visits = enrichment.get("synter_monthly_visits", 0)
    paid_pct = enrichment.get("synter_paid_search_pct", 0)
    plan_budget = enrichment.get("mediaplan_total_budget", 0)

    if visits and settings.openai_api_key:
        subject, body = generate_outreach_email(
            settings=settings,
            ceo_name=visitor.visitor_name,
            company_name=visitor.company_name,
            job_title_hiring=visitor.job_title or "growth",
            company_domain=visitor.company_domain,
        )
        # Append media plan context if we have SimilarWeb data
        if visits > 0:
            plan_snippet = (
                f"\n\nP.S. I pulled your traffic data — {visitor.company_domain} gets "
                f"~{visits:,} monthly visits with {paid_pct:.1f}% from paid channels. "
                f"Happy to share the full analysis."
            )
            body += plan_snippet
    else:
        subject = f"saw you checking out synter"
        body = (
            f"Hi {first_name},\n\n"
            f"Noticed someone from {visitor.company_name} was on our site. "
            f"Curious what caught your eye?\n\n"
            f"We help companies manage Google, Meta, LinkedIn, and Reddit ads "
            f"from one AI-powered platform.\n\n"
            f"Worth a 15-min chat?\n\n"
            f"Best,\n{settings.sender_name or 'Joel'}"
        )

    if settings.dry_run:
        logger.info(
            f"[RB2B DRY RUN] → {visitor.visitor_email} | {visitor.company_name}\n"
            f"  Subject: {subject}\n  Body: {body[:150]}..."
        )
        status = EmailStatus.SKIPPED
    else:
        # Send via Smartlead > Loops > SMTP fallback chain
        success = False
        if settings.smartlead_api_key:
            from engine.outreach.smartlead_sender import send_email as smartlead_send
            success = smartlead_send(
                settings=settings, to_email=visitor.visitor_email,
                to_name=visitor.visitor_name, subject=subject, body=body,
                company_name=visitor.company_name, job_title=visitor.job_title or "",
            )
        elif settings.loops_api_key:
            from engine.outreach.loops_sender import send_email as loops_send
            success = loops_send(
                settings=settings, to_email=visitor.visitor_email,
                to_name=visitor.visitor_name, subject=subject, body=body,
                company_name=visitor.company_name, job_title=visitor.job_title or "",
            )

        status = EmailStatus.SENT if success else EmailStatus.FAILED

    # Log the email
    log_entry = EmailLog(
        company_domain=visitor.company_domain,
        company_name=visitor.company_name,
        contact_name=visitor.visitor_name,
        contact_email=visitor.visitor_email,
        contact_linkedin=visitor.linkedin_url or "",
        job_title_hiring=visitor.job_title or "visitor",
        email_subject=subject,
        email_body_preview=body[:500],
        status=status,
        sent_at=datetime.utcnow() if status == EmailStatus.SENT else None,
    )
    session.add(log_entry)
    session.commit()

    return status == EmailStatus.SENT


def poll_rb2b_visitors(settings: Settings, session: Session) -> int:
    """Poll RB2B API for new visitors and upsert into database.

    Returns number of new visitors added.
    """
    from engine.clients.rb2b import RB2BClient, upsert_visitor

    try:
        client = RB2BClient(settings)
    except ValueError:
        logger.warning("[RB2B] API key not configured")
        return 0

    visitors = client.get_recent_visitors(days=settings.rb2b_poll_days)
    new_count = 0

    for v in visitors:
        normalized = {
            "visitor_email": v.get("email", ""),
            "visitor_name": v.get("full_name", ""),
            "company_name": v.get("company_name", ""),
            "company_domain": v.get("company_domain", ""),
            "job_title": v.get("job_title", ""),
            "linkedin_url": v.get("linkedin_url", ""),
            "page_url": v.get("page_url", ""),
        }
        if normalized["visitor_email"]:
            result = upsert_visitor(session, normalized)
            if result.visit_count == 1:
                new_count += 1

    logger.info(f"[RB2B] Polled {len(visitors)} visitors, {new_count} new")
    return new_count


def main():
    """CLI entry point for RB2B pipeline."""
    parser = argparse.ArgumentParser(description="RB2B visitor outreach pipeline")
    parser.add_argument("--webhook", action="store_true", help="Start webhook server")
    parser.add_argument("--poll", action="store_true", help="Poll RB2B API (default)")
    parser.add_argument("--dry-run", action="store_true", help="Log but don't send")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()

    if args.dry_run:
        settings.dry_run = True

    if args.webhook:
        _start_webhook_server(settings)
    else:
        session = get_session(settings)
        # Poll for new visitors
        poll_rb2b_visitors(settings, session)
        # Process and send outreach
        stats = run_rb2b_pipeline(settings, session)
        print(f"RB2B pipeline: {stats}")


def _start_webhook_server(settings: Settings):
    """Start a minimal webhook server for RB2B callbacks."""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
    except ImportError:
        print("http.server not available")
        sys.exit(1)

    class RB2BWebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/webhooks/rb2b":
                self.send_response(404)
                self.end_headers()
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                from engine.clients.rb2b import parse_webhook_payload, upsert_visitor

                payload = json.loads(body)
                visitor = parse_webhook_payload(payload)

                if visitor:
                    session = get_session(settings)
                    upsert_visitor(session, visitor)

                    if settings.rb2b_auto_enrich:
                        run_rb2b_pipeline(settings, session, source="rb2b_webhook")

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')

            except Exception as exc:
                logger.error(f"[RB2B Webhook] Error: {exc}")
                self.send_response(500)
                self.end_headers()

        def log_message(self, format, *args):
            logger.info(f"[RB2B Webhook] {format % args}")

    port = 8787
    server = HTTPServer(("0.0.0.0", port), RB2BWebhookHandler)
    print(f"RB2B webhook server listening on port {port}")
    print(f"Endpoint: POST http://localhost:{port}/webhooks/rb2b")
    server.serve_forever()


if __name__ == "__main__":
    main()
