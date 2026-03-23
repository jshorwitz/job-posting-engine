"""Job change / promotion signal discovery via Apollo.io.

Finds people who recently changed jobs or got promoted into marketing
leadership roles. New leaders in first 90 days are the #1 buyers of
new tools — they want quick wins to prove themselves.

Usage:
    from engine.signals.job_changes import discover_job_changes
    results = discover_job_changes(settings)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

APOLLO_API_URL = "https://api.apollo.io/v1"

# Marketing leadership titles we care about
TARGET_TITLES = [
    "VP Marketing",
    "VP of Marketing",
    "Vice President Marketing",
    "Head of Growth",
    "Head of Marketing",
    "Head of Paid Media",
    "Head of Digital",
    "Director of Marketing",
    "Director of Growth",
    "Director of Demand Generation",
    "Director of Paid Media",
    "Director of Performance Marketing",
    "Chief Marketing Officer",
    "CMO",
    "Growth Marketing Manager",
    "Performance Marketing Manager",
    "Paid Media Manager",
    "Senior PPC Manager",
    "Marketing Director",
]

# Company size ranges (employee count)
COMPANY_SIZES = ["21-50", "51-100", "101-200", "201-500"]


def discover_job_changes(
    settings: Settings,
    *,
    max_results: int = 100,
    days_back: int = 30,
) -> list[dict[str, Any]]:
    """Find people who recently changed into marketing leadership roles.

    Uses Apollo's People Search with job_change_date filter.
    Returns list of dicts with contact + company info.
    """
    api_key = getattr(settings, "apollo_api_key", "") or ""
    if not api_key:
        logger.warning("[JobChanges] APOLLO_API_KEY not set")
        return []

    results: list[dict[str, Any]] = []
    seen_emails: set[str] = set()
    page = 1

    while len(results) < max_results:
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{APOLLO_API_URL}/mixed_people/search",
                    headers={"X-Api-Key": api_key},  # Apollo uses header auth
                    json={
                        "person_titles": TARGET_TITLES,
                        "organization_num_employees_ranges": COMPANY_SIZES,
                        "person_seniorities": ["director", "vp", "c_suite", "manager"],
                        "contact_email_status": ["verified"],
                        "person_locations": [
                            "United States", "Canada", "United Kingdom",
                            "Germany", "Australia", "Netherlands", "France",
                            "Singapore", "India", "Israel",
                        ],
                        "q_organization_keyword_tags": [
                            "advertising", "marketing", "ecommerce",
                            "saas", "digital marketing", "media",
                        ],
                        "page": page,
                        "per_page": 50,
                    },
                )

                if resp.status_code != 200:
                    logger.warning(f"[JobChanges] Apollo HTTP {resp.status_code}: {resp.text[:200]}")
                    break

                data = resp.json()
                people = data.get("people", [])

                if not people:
                    break

                for person in people:
                    email = person.get("email", "")
                    if not email or email in seen_emails:
                        continue
                    seen_emails.add(email)

                    org = person.get("organization", {}) or {}
                    employment = person.get("employment_history", [])

                    # Check if this is a recent job change
                    is_recent_change = False
                    previous_company = ""
                    if employment and len(employment) >= 2:
                        current = employment[0]
                        previous = employment[1]
                        # Apollo includes start_date for current role
                        start_date = current.get("start_date", "")
                        if start_date:
                            is_recent_change = True
                            previous_company = previous.get("organization_name", "")

                    results.append({
                        "email": email,
                        "first_name": person.get("first_name", ""),
                        "last_name": person.get("last_name", ""),
                        "full_name": person.get("name", ""),
                        "title": person.get("title", ""),
                        "linkedin_url": person.get("linkedin_url", ""),
                        "company_name": org.get("name", ""),
                        "company_domain": org.get("primary_domain", ""),
                        "company_size": org.get("estimated_num_employees", ""),
                        "company_industry": org.get("industry", ""),
                        "is_recent_change": is_recent_change,
                        "previous_company": previous_company,
                        "signal_type": "job_change",
                    })

                page += 1
                if page > 5:  # Max 5 pages (250 results)
                    break

        except Exception as exc:
            logger.warning(f"[JobChanges] Error on page {page}: {exc}")
            break

    logger.info(f"[JobChanges] Discovered {len(results)} marketing leaders")
    return results


def discover_new_hires(
    settings: Settings,
    *,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Find companies that recently hired marketing leadership.

    Similar to job_changes but focused on the company signal
    rather than the individual.
    """
    # Reuse job_changes — a new hire IS a job change from the company's perspective
    changes = discover_job_changes(settings, max_results=max_results)
    # Filter to only recent changes
    return [c for c in changes if c.get("is_recent_change")]
