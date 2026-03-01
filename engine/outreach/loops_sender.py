"""Loops.so transactional email sender.

Uses the Loops transactional API to send personalized outreach emails
with built-in deliverability, open/click tracking, and unsubscribe handling.

API docs: https://loops.so/docs/api-reference/send-transactional-email

Setup:
  1. Create a transactional email in Loops with these data variables:
     - {{firstName}}  — recipient first name
     - {{subject}}    — email subject line
     - {{body}}       — email body (plain text or HTML)
     - {{companyName}} — recipient's company
     - {{jobTitle}}   — the role they're hiring for
  2. Copy the transactionalId and set LOOPS_TRANSACTIONAL_ID in .env
  3. Set LOOPS_API_KEY in .env
"""

from __future__ import annotations

import logging

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

LOOPS_API_URL = "https://app.loops.so/api/v1"


def send_email(
    settings: Settings,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    company_name: str = "",
    job_title: str = "",
) -> bool:
    """Send an outreach email via Loops transactional API.

    Returns True on success, False on failure.
    """
    if not settings.loops_api_key:
        logger.warning("LOOPS_API_KEY not set — cannot send email")
        return False

    if not settings.loops_transactional_id:
        logger.warning(
            "LOOPS_TRANSACTIONAL_ID not set — create a transactional email "
            "in Loops and set the ID in .env"
        )
        return False

    first_name = to_name.split()[0] if to_name else "there"

    payload = {
        "email": to_email,
        "transactionalId": settings.loops_transactional_id,
        "dataVariables": {
            "firstName": first_name,
            "subject": subject,
            "body": body,
            "companyName": company_name,
            "jobTitle": job_title,
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.loops_api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{LOOPS_API_URL}/transactional",
                headers=headers,
                json=payload,
            )

        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                logger.info(f"Loops: email sent → {to_email} | Subject: {subject}")
                return True
            else:
                logger.error(f"Loops: send failed for {to_email}: {data}")
                return False

        logger.error(f"Loops: {resp.status_code} — {resp.text[:300]}")
        return False

    except httpx.TimeoutException:
        logger.error(f"Loops: timeout sending to {to_email}")
        return False


def add_contact(
    settings: Settings,
    email: str,
    first_name: str = "",
    last_name: str = "",
    company: str = "",
    source: str = "job-posting-engine",
) -> bool:
    """Add or update a contact in Loops for future campaigns.

    Returns True on success.
    """
    if not settings.loops_api_key:
        return False

    payload = {
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "source": source,
        "subscribed": True,
    }
    if company:
        payload["company"] = company

    headers = {
        "Authorization": f"Bearer {settings.loops_api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{LOOPS_API_URL}/contacts/create",
                headers=headers,
                json=payload,
            )

        if resp.status_code == 200:
            logger.info(f"Loops: contact added — {email}")
            return True

        logger.warning(f"Loops: contact create {resp.status_code} — {resp.text[:200]}")
        return False

    except Exception as exc:
        logger.warning(f"Loops: contact create failed — {exc}")
        return False
