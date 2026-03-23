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


def enrich_person_apollo(
    settings: Settings,
    *,
    first_name: str = "",
    last_name: str = "",
    domain: str = "",
    linkedin_url: str = "",
) -> dict[str, Any] | None:
    """Enrich a person via Apollo people/match (works on free plan).

    Returns full profile with email, title, employment history.
    """
    api_key = getattr(settings, "apollo_api_key", "") or ""
    if not api_key:
        return None

    payload: dict[str, Any] = {}
    if first_name:
        payload["first_name"] = first_name
    if last_name:
        payload["last_name"] = last_name
    if domain:
        payload["organization_domain"] = domain
    if linkedin_url:
        payload["linkedin_url"] = linkedin_url

    if not payload:
        return None

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{APOLLO_API_URL}/people/match",
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code != 200:
                return None

            person = resp.json().get("person")
            if not person:
                return None

            org = person.get("organization", {}) or {}
            employment = person.get("employment_history", []) or []

            # Detect recent job change
            is_recent_change = False
            previous_company = ""
            if len(employment) >= 2:
                current = employment[0]
                start_date = current.get("start_date", "")
                if start_date:
                    # Check if started within last 6 months
                    try:
                        from datetime import datetime
                        start = datetime.strptime(start_date[:10], "%Y-%m-%d")
                        days_ago = (datetime.now() - start).days
                        if days_ago <= 180:
                            is_recent_change = True
                            previous_company = employment[1].get("organization_name", "")
                    except Exception:
                        pass

            return {
                "email": person.get("email", ""),
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
            }

    except Exception as exc:
        logger.warning(f"[JobChanges] Apollo match error: {exc}")
        return None


def discover_job_changes(
    settings: Settings,
    *,
    max_results: int = 100,
    days_back: int = 30,
) -> list[dict[str, Any]]:
    """Find marketing leaders via Apollo people/match.

    Uses Serper to find recent "new CMO" / "new VP Marketing" announcements,
    then enriches with Apollo to get email + employment history.
    """
    api_key = getattr(settings, "apollo_api_key", "") or ""
    serper_key = getattr(settings, "serper_api_key", "") or ""

    if not api_key:
        logger.warning("[JobChanges] APOLLO_API_KEY not set")
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Use Serper to find recent leadership announcements
    queries = [
        "new VP Marketing hired 2026",
        "new Head of Growth appointed 2026",
        "new CMO named 2026",
        "new Director of Marketing joins 2026",
        "new Head of Paid Media hired",
        "appointed Chief Marketing Officer 2026",
        "joins as VP Growth 2026",
        "named Head of Digital Marketing",
        "new Director Demand Generation",
        "promoted VP Marketing",
    ]

    if serper_key:
        logger.info("[JobChanges] Discovering leadership changes via Serper News...")
        for query in queries:
            if len(results) >= max_results:
                break
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(
                        "https://google.serper.dev/news",
                        headers={"X-API-KEY": serper_key},
                        json={"q": query, "num": 10},
                    )
                    if resp.status_code != 200:
                        continue

                    for item in resp.json().get("news", []):
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")

                        # Extract person name and company from title
                        import re
                        # Pattern: "PersonName joins/named/appointed CompanyName as Title"
                        patterns = [
                            r'(\w+\s+\w+)\s+(?:joins|named|appointed|hired|promoted)\s+(?:at|as|to)\s+(\w[\w\s&]+)',
                            r'(\w[\w\s&]+?)\s+(?:hires|appoints|names|promotes)\s+(\w+\s+\w+)\s+as',
                        ]

                        for pattern in patterns:
                            m = re.search(pattern, title, re.IGNORECASE)
                            if m:
                                # Try to enrich with Apollo
                                name_or_company = m.group(1).strip()
                                company_or_name = m.group(2).strip()

                                # Try Serper to find the company domain
                                domain_resp = client.post(
                                    "https://google.serper.dev/search",
                                    headers={"X-API-KEY": serper_key},
                                    json={"q": f"{company_or_name} company website", "num": 1},
                                )
                                if domain_resp.status_code == 200:
                                    organic = domain_resp.json().get("organic", [])
                                    if organic:
                                        from urllib.parse import urlparse
                                        domain = urlparse(organic[0].get("link", "")).netloc.replace("www.", "")

                                        if domain and domain not in seen:
                                            seen.add(domain)
                                            # Enrich with Apollo
                                            parts = name_or_company.split()
                                            if len(parts) >= 2:
                                                enriched = enrich_person_apollo(
                                                    settings,
                                                    first_name=parts[0],
                                                    last_name=" ".join(parts[1:]),
                                                    domain=domain,
                                                )
                                                if enriched and enriched.get("email"):
                                                    results.append(enriched)
                                                    logger.info(f"[JobChanges] Found: {enriched['email']} | {enriched['full_name']} @ {enriched['company_name']}")
                                break

            except Exception as exc:
                logger.warning(f"[JobChanges] Error: {exc}")
                continue

    logger.info(f"[JobChanges] Discovered {len(results)} marketing leaders")
    return results


def discover_new_hires(
    settings: Settings,
    *,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Find companies that recently hired marketing leadership."""
    changes = discover_job_changes(settings, max_results=max_results)
    return [c for c in changes if c.get("is_recent_change")]
