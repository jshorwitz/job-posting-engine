"""Pre-send quality filters for Vector visitor outreach."""

from __future__ import annotations

from typing import Protocol


class VectorVisitorLike(Protocol):
    visitor_email: str
    visitor_name: str


PERSONAL_EMAIL_DOMAINS = {
    "aol.com",
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "me.com",
    "msn.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}


def should_skip_vector_visitor(visitor: VectorVisitorLike) -> tuple[bool, str]:
    """Return whether a Vector visitor should be skipped before outreach."""
    email = (visitor.visitor_email or "").strip().lower()
    if "@" not in email:
        return True, "missing or invalid email"

    email_domain = email.rsplit("@", 1)[1]
    if email_domain in PERSONAL_EMAIL_DOMAINS:
        return True, f"personal email domain: {email_domain}"

    if not (visitor.visitor_name or "").strip():
        return True, "missing contact name"

    return False, ""
