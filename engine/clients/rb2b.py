"""RB2B.com client — website visitor identification for outbound campaigns.

RB2B identifies anonymous website visitors and provides company + contact
data. This module handles both webhook ingestion and API polling to feed
identified visitors into the outreach pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from engine.config import Settings
from engine.db.models import RB2BVisitor

logger = logging.getLogger(__name__)

RB2B_API_BASE = "https://api.rb2b.com/v1"


class RB2BClient:
    """Client for RB2B.com visitor identification API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.rb2b_api_key:
            raise ValueError("RB2B_API_KEY is required")
        self._api_key = settings.rb2b_api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def get_recent_visitors(self, days: int = 7) -> list[dict[str, Any]]:
        """Fetch recently identified visitors from RB2B API.

        Returns list of visitor dicts with email, name, company info.
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{RB2B_API_BASE}/visitors",
                    headers=self._headers,
                    params={"days": days, "limit": 100},
                )
                if resp.status_code != 200:
                    logger.warning(f"[RB2B] HTTP {resp.status_code}")
                    return []

                data = resp.json()
                return data.get("visitors", [])

        except Exception as exc:
            logger.warning(f"[RB2B] Failed to fetch visitors: {exc}")
            return []


def parse_webhook_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse an RB2B webhook payload into a normalized visitor dict.

    Expected payload fields (RB2B webhook format):
      - email, first_name, last_name, full_name
      - company_name, company_domain
      - job_title, linkedin_url
      - page_url, visited_at
    """
    email = payload.get("email")
    if not email:
        logger.info("[RB2B] Webhook payload missing email, skipping")
        return None

    return {
        "visitor_email": email,
        "visitor_name": payload.get("full_name") or f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip(),
        "company_name": payload.get("company_name", ""),
        "company_domain": payload.get("company_domain", ""),
        "job_title": payload.get("job_title", ""),
        "linkedin_url": payload.get("linkedin_url", ""),
        "page_url": payload.get("page_url", ""),
        "visited_at": payload.get("visited_at") or datetime.utcnow().isoformat(),
        "source": "rb2b_webhook",
    }


def upsert_visitor(session: Session, visitor: dict[str, Any]) -> RB2BVisitor:
    """Insert or update an RB2B visitor record. Returns the model instance."""
    existing = (
        session.query(RB2BVisitor)
        .filter_by(visitor_email=visitor["visitor_email"])
        .first()
    )

    if existing:
        existing.visit_count = (existing.visit_count or 1) + 1
        existing.last_visited_at = datetime.utcnow()
        existing.last_page_url = visitor.get("page_url", "")
        session.commit()
        logger.info(f"[RB2B] Updated visitor: {visitor['visitor_email']} (visit #{existing.visit_count})")
        return existing

    new_visitor = RB2BVisitor(
        visitor_email=visitor["visitor_email"],
        visitor_name=visitor.get("visitor_name", ""),
        company_name=visitor.get("company_name", ""),
        company_domain=visitor.get("company_domain", ""),
        job_title=visitor.get("job_title", ""),
        linkedin_url=visitor.get("linkedin_url", ""),
        last_page_url=visitor.get("page_url", ""),
        visit_count=1,
    )
    session.add(new_visitor)
    session.commit()
    logger.info(f"[RB2B] New visitor: {visitor['visitor_email']} from {visitor.get('company_name', 'unknown')}")
    return new_visitor
