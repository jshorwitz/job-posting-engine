"""SMTP email sender with TLS support."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from engine.config import Settings

logger = logging.getLogger(__name__)


def send_email(
    settings: Settings,
    to_name: str,
    to_linkedin: str | None,
    subject: str,
    body: str,
) -> bool:
    """Send a plain-text outreach email via SMTP.

    Note: Sumble People API returns LinkedIn URLs but not email addresses.
    This function is wired up for when email enrichment is added (e.g. via
    Apollo, Hunter.io, or Prospeo). For now the pipeline logs contacts
    with their LinkedIn URLs for manual outreach.

    Returns True on success, False on failure.
    """
    # For now we don't have email addresses from Sumble — log and skip
    # TODO: Add email enrichment provider (Apollo/Hunter.io/Prospeo)
    logger.warning(
        f"SMTP send skipped — no email address available. "
        f"Contact: {to_name}, LinkedIn: {to_linkedin}"
    )
    return False


def _send_smtp(
    settings: Settings,
    to_address: str,
    to_name: str,
    subject: str,
    body: str,
) -> bool:
    """Actually send via SMTP. Called when email address is available."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.from_name} <{settings.from_email}>"
    msg["To"] = f"{to_name} <{to_address}>"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.from_email, to_address, msg.as_string())

        logger.info(f"Email sent → {to_address} | Subject: {subject}")
        return True

    except smtplib.SMTPException as exc:
        logger.error(f"SMTP error sending to {to_address}: {exc}")
        return False
