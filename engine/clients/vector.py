"""Vector.co client — website visitor de-anonymization for LinkedIn outreach.

Vector.co identifies anonymous website visitors at the contact level
(name, email, job title, company, LinkedIn URL) and fires webhooks
when visitors match ICP segments. This module handles webhook payload
parsing, ICP filtering, and visitor upsert into the database.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from engine.config import Settings
from engine.db.models import VectorVisitor

logger = logging.getLogger(__name__)

# Job title keywords that indicate marketing leadership ICP
_ICP_TITLE_KEYWORDS = [
    "vp",
    "director",
    "head of",
    "cmo",
    "chief marketing",
    "marketing",
    "growth",
    "demand",
    "performance",
    "paid media",
    "digital",
]


def parse_webhook_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a Vector.co webhook payload into a normalized visitor dict.

    Vector uses Svix for webhooks. Payloads arrive in an event envelope::

        {
            "type": "contact.visited",
            "data": { ...contact fields... }
        }

    Supported event types:
      - contact.visited        — site visitor identified
      - contact.intentDetected — off-site intent signal

    Returns None for non-contact events or missing email.
    """
    event_type = payload.get("type", "")

    if not event_type.startswith("contact."):
        logger.debug("[Vector] Ignoring event type: %s", event_type)
        return None

    # Extract contact data from Svix envelope
    data = payload.get("data", payload)

    email = data.get("email")
    if not email:
        logger.info("[Vector] Webhook payload missing email, skipping")
        return None

    source = "vector_intent" if event_type == "contact.intentDetected" else "vector_visited"

    return {
        "visitor_email": email,
        "visitor_name": data.get("full_name") or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
        "company_name": data.get("company_name", ""),
        "company_domain": data.get("company_domain", ""),
        "job_title": data.get("job_title", ""),
        "linkedin_url": data.get("linkedin_url", ""),
        "page_url": data.get("page_url", ""),
        "visited_at": data.get("visited_at") or datetime.utcnow().isoformat(),
        "seniority": data.get("seniority", ""),
        "industry": data.get("industry", ""),
        "employee_count": data.get("employee_count"),
        "intent_topics": data.get("intent_topics", []),
        "source": source,
    }


def is_icp_match(visitor: dict[str, Any]) -> bool:
    """Check if a visitor matches the ideal customer profile.

    Returns True if the visitor's job title contains any marketing
    leadership keyword, indicating they're likely involved in ad spend
    decisions.
    """
    title = (visitor.get("job_title") or "").lower()
    if not title:
        return False

    return any(kw in title for kw in _ICP_TITLE_KEYWORDS)


def upsert_visitor(session: Session, visitor: dict[str, Any]) -> VectorVisitor:
    """Insert or update a Vector visitor record. Returns the model instance."""
    existing = (
        session.query(VectorVisitor)
        .filter_by(visitor_email=visitor["visitor_email"])
        .first()
    )

    if existing:
        existing.visit_count = (existing.visit_count or 1) + 1
        existing.last_visited_at = datetime.utcnow()
        existing.last_page_url = visitor.get("page_url", "")
        existing.job_title = visitor.get("job_title", "") or existing.job_title
        existing.linkedin_url = visitor.get("linkedin_url") or existing.linkedin_url
        existing.seniority = visitor.get("seniority", "") or existing.seniority
        session.commit()
        logger.info(f"[Vector] Updated visitor: {visitor['visitor_email']} (visit #{existing.visit_count})")
        return existing

    new_visitor = VectorVisitor(
        visitor_email=visitor["visitor_email"],
        visitor_name=visitor.get("visitor_name", ""),
        company_name=visitor.get("company_name", ""),
        company_domain=visitor.get("company_domain", ""),
        job_title=visitor.get("job_title", ""),
        seniority=visitor.get("seniority", ""),
        linkedin_url=visitor.get("linkedin_url", ""),
        last_page_url=visitor.get("page_url", ""),
        icp_match=is_icp_match(visitor),
        source=visitor.get("source", "vector_webhook"),
        visit_count=1,
    )
    session.add(new_visitor)
    session.commit()
    logger.info(f"[Vector] New visitor: {visitor['visitor_email']} from {visitor.get('company_name', 'unknown')}")
    return new_visitor
