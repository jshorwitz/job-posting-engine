"""Smartlead.ai email sender — cold outreach via Smartlead campaigns.

Smartlead handles email warmup, rotation, and deliverability optimization.
This module sends individual emails or adds leads to Smartlead campaigns.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

SMARTLEAD_API_BASE = "https://server.smartlead.ai/api/v1"


def send_email(
    settings: Settings,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    company_name: str = "",
    job_title: str = "",
    campaign_id_override: str = "",
    custom_fields: dict[str, str] | None = None,
) -> bool:
    """Add a lead to a Smartlead campaign and trigger the email sequence.

    This adds the lead to the configured campaign. Smartlead handles
    sending, warmup, rotation, and follow-up scheduling.
    """
    if not settings.smartlead_api_key:
        logger.warning("[Smartlead] API key not configured")
        return False

    campaign_id = campaign_id_override or settings.smartlead_campaign_id
    if not campaign_id:
        logger.warning("[Smartlead] Campaign ID not configured")
        return False

    # Split name into first/last
    parts = to_name.split(maxsplit=1) if to_name else ["", ""]
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""

    merged_custom_fields = {
        "job_title": job_title,
        "email_subject": subject,
        "email_body": body,
    }
    if custom_fields:
        merged_custom_fields.update(
            {key: value for key, value in custom_fields.items() if value is not None}
        )

    lead_payload = {
        "lead_list": [
            {
                "email": to_email,
                "first_name": first_name,
                "last_name": last_name,
                "company_name": company_name,
                "custom_fields": merged_custom_fields,
            }
        ],
        "settings": {
            "ignore_global_block_list": False,
            "ignore_unsubscribe_list": False,
            "ignore_duplicate_leads_in_other_campaign": False,
        },
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/leads",
                params={"api_key": settings.smartlead_api_key},
                json=lead_payload,
            )

            if resp.status_code in (200, 201):
                logger.info(f"[Smartlead] Lead added: {to_email} → campaign {campaign_id}")
                return True
            else:
                logger.warning(
                    f"[Smartlead] Failed to add lead {to_email}: "
                    f"HTTP {resp.status_code} — {resp.text[:200]}"
                )
                return False

    except Exception as exc:
        logger.error(f"[Smartlead] Error adding lead {to_email}: {exc}")
        return False


def create_campaign(
    settings: Settings,
    name: str,
    from_email: str | None = None,
) -> str | None:
    """Create a new Smartlead campaign. Returns campaign ID or None."""
    if not settings.smartlead_api_key:
        return None

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{SMARTLEAD_API_BASE}/campaigns/create",
                params={"api_key": settings.smartlead_api_key},
                json={"name": name},
            )

            if resp.status_code in (200, 201):
                campaign_id = resp.json().get("id")
                logger.info(f"[Smartlead] Campaign created: {name} → {campaign_id}")
                return str(campaign_id)
            else:
                logger.warning(f"[Smartlead] Failed to create campaign: {resp.text[:200]}")
                return None

    except Exception as exc:
        logger.error(f"[Smartlead] Error creating campaign: {exc}")
        return None


def get_campaign_stats(settings: Settings, campaign_id: str) -> dict[str, Any] | None:
    """Fetch campaign statistics from Smartlead."""
    if not settings.smartlead_api_key:
        return None

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/analytics",
                params={"api_key": settings.smartlead_api_key},
            )

            if resp.status_code == 200:
                return resp.json()
            return None

    except Exception as exc:
        logger.warning(f"[Smartlead] Error fetching stats: {exc}")
        return None
