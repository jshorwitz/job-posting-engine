"""EmailBison API client — cold outreach via isolated email sequencing.

EmailBison handles email warmup, IP isolation, and deliverability optimization.
Leads are created with custom variables, then attached to campaigns that handle
the multi-step sequence.

API docs: https://docs.emailbison.com
API ref:  https://dedi.emailbison.com/api/reference
Auth:     Bearer token
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)


class EmailBisonClient:
    """Client for the EmailBison REST API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.emailbison_api_key:
            raise ValueError("EMAILBISON_API_KEY is required")
        self._api_key = settings.emailbison_api_key
        self._base_url = settings.emailbison_base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # ── Leads ────────────────────────────────────────────────────────

    def create_lead(
        self,
        email: str,
        first_name: str,
        last_name: str = "",
        company: str = "",
        title: str = "",
        notes: str = "",
        custom_variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        """Create a single lead. Returns the lead data or None on failure.

        Custom variables must be pre-created in the EmailBison workspace.
        Pass them as: [{"name": "email_subject", "value": "..."}]
        """
        payload: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
        }
        if company:
            payload["company"] = company
        if title:
            payload["title"] = title
        if notes:
            payload["notes"] = notes
        if custom_variables:
            payload["custom_variables"] = custom_variables

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self._base_url}/api/leads",
                    headers=self._headers,
                    json=payload,
                )

            if resp.status_code in (200, 201):
                data = resp.json()
                lead_id = data.get("id") or data.get("data", {}).get("id")
                logger.info(f"[EmailBison] Lead created: {email} (id={lead_id})")
                return data
            elif resp.status_code == 422:
                # Likely duplicate — try to find existing lead
                logger.info(f"[EmailBison] Lead may exist: {email} — {resp.text[:200]}")
                return None
            else:
                logger.warning(
                    f"[EmailBison] Failed to create lead {email}: "
                    f"HTTP {resp.status_code} — {resp.text[:200]}"
                )
                return None

        except Exception as exc:
            logger.error(f"[EmailBison] Error creating lead {email}: {exc}")
            return None

    def update_lead(
        self,
        lead_id: int,
        custom_variables: list[dict[str, str]] | None = None,
        **kwargs: str,
    ) -> bool:
        """Update an existing lead by ID."""
        payload: dict[str, Any] = {k: v for k, v in kwargs.items() if v}
        if custom_variables:
            payload["custom_variables"] = custom_variables

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.put(
                    f"{self._base_url}/api/leads/{lead_id}",
                    headers=self._headers,
                    json=payload,
                )

            if resp.status_code == 200:
                logger.info(f"[EmailBison] Lead {lead_id} updated")
                return True

            logger.warning(f"[EmailBison] Failed to update lead {lead_id}: {resp.status_code}")
            return False

        except Exception as exc:
            logger.error(f"[EmailBison] Error updating lead {lead_id}: {exc}")
            return False

    def find_lead(self, email: str) -> dict[str, Any] | None:
        """Search for a lead by email. Returns lead data or None."""
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{self._base_url}/api/leads",
                    headers=self._headers,
                    params={"search": email},
                )

            if resp.status_code == 200:
                data = resp.json()
                leads = data.get("data", [])
                for lead in leads:
                    if lead.get("email", "").lower() == email.lower():
                        return lead
            return None

        except Exception as exc:
            logger.error(f"[EmailBison] Error searching lead {email}: {exc}")
            return None

    # ── Campaigns ────────────────────────────────────────────────────

    def attach_leads_to_campaign(
        self,
        campaign_id: int,
        lead_ids: list[int],
    ) -> bool:
        """Attach leads to a campaign by their IDs."""
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self._base_url}/api/campaigns/{campaign_id}/leads/attach-leads",
                    headers=self._headers,
                    json={"lead_ids": lead_ids},
                )

            if resp.status_code in (200, 201):
                logger.info(
                    f"[EmailBison] {len(lead_ids)} lead(s) attached to campaign {campaign_id}"
                )
                return True

            logger.warning(
                f"[EmailBison] Failed to attach leads to campaign {campaign_id}: "
                f"HTTP {resp.status_code} — {resp.text[:200]}"
            )
            return False

        except Exception as exc:
            logger.error(f"[EmailBison] Error attaching leads to campaign: {exc}")
            return False

    def get_campaigns(self) -> list[dict[str, Any]]:
        """List all campaigns in the workspace."""
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{self._base_url}/api/campaigns",
                    headers=self._headers,
                )

            if resp.status_code == 200:
                return resp.json().get("data", [])
            return []

        except Exception as exc:
            logger.error(f"[EmailBison] Error fetching campaigns: {exc}")
            return []

    # ── High-level helpers ───────────────────────────────────────────

    def add_lead_to_campaign(
        self,
        campaign_id: int,
        email: str,
        first_name: str,
        last_name: str = "",
        company: str = "",
        custom_variables: list[dict[str, str]] | None = None,
    ) -> bool:
        """Create a lead (or find existing) and attach to a campaign.

        This is the main entry point for the outreach pipeline.
        """
        # Try to find existing lead first
        existing = self.find_lead(email)
        if existing:
            lead_id = existing.get("id")
            if lead_id and custom_variables:
                self.update_lead(lead_id, custom_variables=custom_variables)
        else:
            result = self.create_lead(
                email=email,
                first_name=first_name,
                last_name=last_name,
                company=company,
                custom_variables=custom_variables,
            )
            if not result:
                return False
            lead_id = result.get("id") or result.get("data", {}).get("id")

        if not lead_id:
            logger.error(f"[EmailBison] No lead ID for {email}")
            return False

        return self.attach_leads_to_campaign(campaign_id, [lead_id])
