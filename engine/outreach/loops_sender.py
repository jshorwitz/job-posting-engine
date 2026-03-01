"""Loops.so campaign email sender.

Adds contacts to a Loops mailing list with personalized properties
(emailBody, companyName, jobTitle) so campaigns can render {{emailBody}}.

The campaign itself is created and sent from the Loops UI or triggered
via a Loop automation on the "outreach_ready" event.

API docs: https://loops.so/docs/api-reference

Setup:
  1. Create a mailing list in Loops called "Cold Outreach" (or similar).
  2. Set LOOPS_MAILING_LIST_ID in .env (from the list settings page).
  3. Create a campaign using the cold-outreach MJML template.
  4. Set LOOPS_API_KEY in .env.
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
    """Add a contact to the outreach mailing list with personalized data.

    The actual email is sent when the campaign is triggered from Loops.
    Returns True on success, False on failure.
    """
    if not settings.loops_api_key:
        logger.warning("LOOPS_API_KEY not set — cannot send email")
        return False

    if not body or not body.strip():
        logger.error(f"Loops: refusing to queue blank email for {to_email}")
        return False

    if not subject or not subject.strip():
        logger.error(f"Loops: refusing to queue email without subject for {to_email}")
        return False

    first_name = to_name.split()[0] if to_name else ""
    last_name = " ".join(to_name.split()[1:]) if to_name else ""

    # Convert newlines to <br> for HTML rendering in Loops
    html_body = body.replace("\n", "<br>")

    # Loops limits custom property values to ~500 chars
    if len(html_body) > 500:
        logger.warning(
            f"Loops: emailBody is {len(html_body)} chars (limit ~500) for {to_email}, truncating"
        )
        html_body = html_body[:497] + "..."

    # Add/update contact with personalized properties
    success = add_contact(
        settings=settings,
        email=to_email,
        first_name=first_name,
        last_name=last_name,
        company=company_name,
        source="job-posting-engine",
        custom_properties={
            "emailBody": html_body,
            "emailSubject": subject,
            "companyName": company_name,
            "jobTitle": job_title,
        },
    )

    if not success:
        return False

    # Fire event so a Loop automation can trigger the send.
    # Note: the MJML template uses {emailBody} which reads CONTACT properties.
    # Event properties are only for automation trigger filtering, not template rendering.
    event_ok = _send_event(
        settings=settings,
        email=to_email,
        event_name="outreach_ready",
        properties={
            "companyName": company_name,
            "jobTitle": job_title,
        },
    )

    if not event_ok:
        logger.error(f"Loops: event send failed for {to_email} — email may not trigger")
        return False

    logger.info(f"Loops: contact queued for outreach → {to_email} | {subject}")
    return True


def add_contact(
    settings: Settings,
    email: str,
    first_name: str = "",
    last_name: str = "",
    company: str = "",
    source: str = "job-posting-engine",
    custom_properties: dict | None = None,
) -> bool:
    """Add or update a contact in Loops.

    Returns True on success.
    """
    if not settings.loops_api_key:
        return False

    payload: dict = {
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "source": source,
        "subscribed": True,
    }
    if company:
        payload["company"] = company
    if custom_properties:
        for key, value in custom_properties.items():
            payload[key] = value

    # Add to mailing list if configured
    if settings.loops_mailing_list_id:
        payload["mailingLists"] = {settings.loops_mailing_list_id: True}

    headers = {
        "Authorization": f"Bearer {settings.loops_api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            # Use update (upsert) endpoint — creates if not found, updates if exists.
            # This avoids the create-then-409-retry pattern.
            resp = client.put(
                f"{LOOPS_API_URL}/contacts/update",
                headers=headers,
                json=payload,
            )

        if resp.status_code == 200:
            logger.info(f"Loops: contact upserted — {email}")
            return True

        logger.warning(f"Loops: contact upsert {resp.status_code} — {resp.text[:200]}")
        return False

    except Exception as exc:
        logger.warning(f"Loops: contact upsert failed — {exc}")
        return False


def _send_event(
    settings: Settings,
    email: str,
    event_name: str,
    properties: dict | None = None,
) -> bool:
    """Send an event to Loops to trigger automations."""
    headers = {
        "Authorization": f"Bearer {settings.loops_api_key}",
        "Content-Type": "application/json",
    }

    payload: dict = {
        "email": email,
        "eventName": event_name,
    }
    if properties:
        payload["eventProperties"] = properties

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{LOOPS_API_URL}/events/send",
                headers=headers,
                json=payload,
            )

        if resp.status_code == 200:
            logger.debug(f"Loops: event '{event_name}' sent for {email}")
            return True

        logger.warning(f"Loops: event send {resp.status_code} — {resp.text[:200]}")
        return False

    except Exception as exc:
        logger.warning(f"Loops: event send failed — {exc}")
        return False
