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
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
) -> bool:
    """Send a plain-text outreach email via SMTP.

    Returns True on success, False on failure.
    """
    if not settings.smtp_user or not settings.smtp_pass:
        logger.warning(
            f"SMTP credentials not configured — cannot send to {to_email}. "
            f"Set SMTP_USER and SMTP_PASS in .env"
        )
        return False

    if not settings.from_email:
        logger.warning("FROM_EMAIL not configured — cannot send email")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.from_name} <{settings.from_email}>"
    msg["To"] = f"{to_name} <{to_email}>"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.from_email, to_email, msg.as_string())

        logger.info(f"Email sent → {to_email} | Subject: {subject}")
        return True

    except smtplib.SMTPException as exc:
        logger.error(f"SMTP error sending to {to_email}: {exc}")
        return False
