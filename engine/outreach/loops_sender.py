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


def enrich_for_followup(
    settings: Settings,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    company_name: str = "",
    monthly_spend: float = 0,
    savings_low: float = 0,
    savings_high: float = 0,
    spyfu_data: dict | None = None,
) -> bool:
    """Upsert follow-up data + SpyFu enrichment to contact properties.

    Pushes 18+ custom properties that map to merge tags in the
    manually-created 18-step Loop automation (e.g. {{monthlyAdSpend}},
    {{topCompetitor}}, {{gapKeyword}}).

    No event is fired — the Loop's built-in delay handles timing.
    """
    if not settings.loops_api_key:
        logger.warning("LOOPS_API_KEY not set — cannot enrich for follow-up")
        return False

    if not body or not body.strip():
        logger.error(f"Loops: refusing to upsert blank follow-up for {to_email}")
        return False

    html_body = body.replace("\n", "<br>")
    if len(html_body) > 500:
        html_body = html_body[:497] + "..."

    properties: dict = {
        "followupBody": html_body,
        "followupSubject": subject,
        "companyName": company_name,
    }

    if monthly_spend > 0:
        properties["monthlyAdSpend"] = f"${monthly_spend:,.0f}"
        properties["annualAdSpend"] = f"${monthly_spend * 12:,.0f}"
        properties["estimatedSavings"] = f"${savings_low:,.0f}-${savings_high:,.0f}"

    # SpyFu enrichment — all 18+ data points as Loops contact properties
    if spyfu_data:
        d = spyfu_data
        _set_if(properties, "ppcKeywords", d.get("ppc_keywords"))
        _set_if(properties, "organicKeywords", d.get("organic_keywords"))
        _set_if(properties, "paidClicks", _fmt_int(d.get("paid_clicks")))
        _set_if(properties, "organicClicks", _fmt_int(d.get("organic_clicks")))
        _set_if(properties, "domainStrength", d.get("domain_strength"))
        _set_if(properties, "topCompetitor", d.get("top_competitor"))
        _set_if(properties, "competitorSpend", _fmt_money(d.get("competitor_spend")))
        _set_if(properties, "topHeadline", d.get("top_headline"))
        _set_if(properties, "topAdDays", d.get("top_ad_days"))
        _set_if(properties, "totalAds", d.get("total_ads"))
        _set_if(properties, "orgClickValue", _fmt_money(d.get("organic_click_value")))
        _set_if(properties, "seoTop10", d.get("seo_top10"))
        _set_if(properties, "wasteKeywords", d.get("waste_keywords"))
        _set_if(properties, "estimatedSavingsSpyfu", _fmt_money(d.get("estimated_savings")))

    success = add_contact(
        settings=settings,
        email=to_email,
        source="job-posting-engine",
        custom_properties=properties,
    )

    if success:
        props_count = len([v for v in properties.values() if v])
        logger.info(
            f"Loops: follow-up data upserted for {to_email} | "
            f"{subject} ({props_count} properties)"
        )
    return success


def _set_if(props: dict, key: str, value: object) -> None:
    """Set property only if value is truthy (non-zero, non-empty)."""
    if value:
        props[key] = str(value)


def _fmt_money(amount: float | int | None) -> str:
    """Format a dollar amount for display, or empty string."""
    if not amount:
        return ""
    return f"${amount:,.0f}"


def _fmt_int(value: int | None) -> str:
    """Format an integer with commas, or empty string."""
    if not value:
        return ""
    return f"{value:,}"


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
