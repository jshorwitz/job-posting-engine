"""Vector.co visitor → Smartlead email outreach pipeline.

Receives identified website visitors from Vector.co via webhook,
enriches them with competitive intelligence (SpyFu, BuiltWith, Synter),
generates personalized cold emails, and adds them to a Smartlead campaign.

Usage:
    python -m engine.vector_pipeline --webhook     # start webhook server
    python -m engine.vector_pipeline --dry-run     # process pending visitors
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime

from sqlalchemy.orm import Session

from engine.config import Settings
from engine.db.database import get_session
from engine.db.models import (
    EmailLog,
    EmailStatus,
    VectorVisitor,
)
from engine.ai.vector_visitor_email import render_vector_visitor_sequence
from engine.enrichment import enrich_lead
from engine.vector_filters import should_skip_vector_visitor

logger = logging.getLogger(__name__)


def run_vector_pipeline(
    settings: Settings,
    session: Session,
    *,
    source: str = "vector_webhook",
) -> dict[str, int]:
    """Process Vector visitors: enrich → generate email → send via Smartlead.

    Finds visitors where outreach_sent=False, enriches them,
    generates personalized cold emails, and adds to a Smartlead campaign.
    Deduplicates against EmailLog by visitor_email.
    """
    stats = {"processed": 0, "enriched": 0, "sent": 0, "skipped": 0, "failed": 0}

    visitors = (
        session.query(VectorVisitor)
        .filter_by(outreach_sent=False)
        .filter(VectorVisitor.visitor_email.isnot(None))
        .filter(VectorVisitor.company_domain != "")
        .limit(settings.max_emails_per_run)
        .all()
    )

    if not visitors:
        logger.info("[Vector] No new visitors to process")
        return stats

    logger.info(f"[Vector] Processing {len(visitors)} visitors")

    for visitor in visitors:
        stats["processed"] += 1

        should_skip, skip_reason = should_skip_vector_visitor(visitor)
        if should_skip:
            logger.info(
                f"[Vector] Skipping {visitor.visitor_email}: {skip_reason}"
            )
            visitor.outreach_sent = True
            session.commit()
            stats["skipped"] += 1
            continue

        # Dedup: skip if we already emailed this address
        existing = (
            session.query(EmailLog)
            .filter(EmailLog.contact_email == visitor.visitor_email)
            .filter(EmailLog.status.in_([EmailStatus.SENT, EmailStatus.SKIPPED]))
            .first()
        )
        if existing:
            logger.info(f"[Vector] Already emailed {visitor.visitor_email}, skipping")
            visitor.outreach_sent = True
            session.commit()
            stats["skipped"] += 1
            continue

        # Enrich with all sources
        enrichment = enrich_lead(
            settings=settings,
            domain=visitor.company_domain,
            company_name=visitor.company_name,
            contact_name=visitor.visitor_name,
            job_title_hiring=visitor.job_title or "marketing leader",
        )
        stats["enriched"] += 1

        visitor.enrichment_json = json.dumps(enrichment, default=str)
        session.commit()

        # Use deterministic Vector visitor copy so this campaign stays aligned
        # with the approved website-visitor messaging.
        sequence = render_vector_visitor_sequence(visitor.visitor_name)
        subject, body = sequence.initial.subject, sequence.initial.body

        if settings.dry_run:
            logger.info(
                f"[Vector DRY RUN] → {visitor.visitor_name} @ {visitor.company_name}\n"
                f"  Email: {visitor.visitor_email}\n"
                f"  Subject: {subject}\n  Body: {body[:150]}..."
            )
            email_status = EmailStatus.SKIPPED
        else:
            from engine.outreach.smartlead_sender import send_email as smartlead_send

            success = smartlead_send(
                settings=settings,
                to_email=visitor.visitor_email,
                to_name=visitor.visitor_name,
                subject=subject,
                body=body,
                company_name=visitor.company_name,
                job_title=visitor.job_title or "marketing leader",
                custom_fields={
                    "follow_up_1_subject": sequence.follow_up.subject,
                    "follow_up_1_body": sequence.follow_up.body,
                    "follow_up_2_subject": sequence.final.subject,
                    "follow_up_2_body": sequence.final.body,
                },
            )
            email_status = EmailStatus.SENT if success else EmailStatus.FAILED
            if not success:
                logger.warning(f"[Vector] Smartlead send failed for {visitor.visitor_email}")

        # Log to EmailLog for dedup and reporting
        log_entry = EmailLog(
            company_domain=visitor.company_domain,
            company_name=visitor.company_name,
            contact_name=visitor.visitor_name,
            contact_email=visitor.visitor_email,
            contact_linkedin=visitor.linkedin_url,
            job_title_hiring=visitor.job_title or "visitor",
            email_subject=subject,
            email_body_preview=body[:500],
            status=email_status,
            sent_at=datetime.utcnow() if email_status == EmailStatus.SENT else None,
        )
        session.add(log_entry)

        if email_status == EmailStatus.SENT:
            visitor.outreach_sent = True
            stats["sent"] += 1
        elif email_status == EmailStatus.SKIPPED:
            visitor.outreach_sent = True
            stats["skipped"] += 1
        else:
            stats["failed"] += 1

        session.commit()

    logger.info(
        f"[Vector] Pipeline complete: {stats['processed']} processed, "
        f"{stats['sent']} sent, {stats['skipped']} skipped, {stats['failed']} failed"
    )
    return stats


def _verify_svix_signature(secret: str, raw_body: bytes, headers: dict) -> bool:
    """Verify a Svix webhook signature (used by Vector.co).

    Svix signs with HMAC-SHA256 over "{msg_id}.{timestamp}.{body}".
    The secret is base64-encoded after the ``whsec_`` prefix.
    The signature header is ``v1,{base64_signature}``.
    """
    import base64

    msg_id = headers.get("webhook-id", "")
    timestamp = headers.get("webhook-timestamp", "")
    sig_header = headers.get("webhook-signature", "")

    if not (msg_id and timestamp and sig_header):
        return False

    # Decode the secret (strip whsec_ prefix)
    secret_bytes = secret
    if secret_bytes.startswith("whsec_"):
        secret_bytes = secret_bytes[6:]
    key = base64.b64decode(secret_bytes)

    # Build the signed content
    signed_content = f"{msg_id}.{timestamp}.".encode() + raw_body
    expected = base64.b64encode(
        hmac.new(key, signed_content, hashlib.sha256).digest()
    ).decode()

    # Check against all signatures in header (comma-separated, v1-prefixed)
    for sig in sig_header.split(" "):
        parts = sig.split(",", 1)
        if len(parts) == 2 and parts[0] == "v1":
            if hmac.compare_digest(parts[1], expected):
                return True

    return False


def _start_webhook_server(settings: Settings):
    """Start a minimal webhook server for Vector.co callbacks."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class VectorWebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/webhooks/vector":
                self.send_response(404)
                self.end_headers()
                return

            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)

            try:
                # Verify Svix webhook signature
                if settings.vector_webhook_secret:
                    if not _verify_svix_signature(
                        settings.vector_webhook_secret, raw_body, self.headers,
                    ):
                        logger.warning("[Vector Webhook] Invalid Svix signature")
                        self.send_response(401)
                        self.end_headers()
                        return

                from engine.clients.vector import (
                    is_icp_match,
                    parse_webhook_payload,
                    upsert_visitor,
                )

                payload = json.loads(raw_body)
                visitor = parse_webhook_payload(payload)

                if visitor and is_icp_match(visitor):
                    session = get_session(settings)
                    upsert_visitor(session, visitor)

                    if settings.vector_auto_enrich:
                        run_vector_pipeline(settings, session, source="vector_webhook")

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')

            except Exception as exc:
                logger.error(f"[Vector Webhook] Error: {exc}")
                self.send_response(500)
                self.end_headers()

        def log_message(self, format, *args):
            logger.info(f"[Vector Webhook] {format % args}")

    port = int(os.environ.get("PORT", "8787"))
    server = HTTPServer(("0.0.0.0", port), VectorWebhookHandler)
    print(f"Vector webhook server listening on port {port}")
    print(f"Endpoint: POST http://localhost:{port}/webhooks/vector")
    server.serve_forever()


def main():
    """CLI entry point for Vector pipeline."""
    parser = argparse.ArgumentParser(description="Vector.co visitor → LinkedIn outreach pipeline")
    parser.add_argument("--webhook", action="store_true", help="Start webhook server")
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
        stats = run_vector_pipeline(settings, session)
        print(f"Vector pipeline: {stats}")


if __name__ == "__main__":
    main()
