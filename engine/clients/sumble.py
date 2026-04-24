"""Sumble.com v5 API client — Jobs + People endpoints.

API docs: https://docs.sumble.com/api
Base URL: https://api.sumble.com/v5
Auth:     Bearer token in Authorization header
Rate:     10 requests/second

Credit costs:
  - Jobs find:           2 credits per job (3 with descriptions)
  - Jobs related people: 1 credit per person returned
  - People find:         1 credit per person returned
  - Org find:            5 credits per result
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.12  # stay under 10 req/s


class SumbleClient:
    """Thin wrapper around the Sumble v3 REST API."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.sumble_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.sumble_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "GrowthEngine/1.0",
        }

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def find_jobs(
        self,
        query: str = "Head of Growth",
        technologies: list[str] | None = None,
        countries: list[str] | None = None,
        limit: int = 50,
        since: str | None = None,
        location_keywords: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for job postings using technology filters + title matching.

        Strategy:
          1. Use Sumble's native `technologies` filter to find companies
             hiring for roles that mention Google Ads, Facebook Ads, etc.
          2. Optionally filter by title keywords client-side (e.g. "Head
             of Growth") for tighter targeting.

        Returns list of job dicts with keys:
            id, organization_id, organization_name, organization_domain,
            job_title, datetime_pulled, primary_job_function, location,
            teams, description, url, matched_technologies
        """
        # Normalise location keywords for client-side filtering
        _location_kws = [kw.lower() for kw in location_keywords] if location_keywords else []

        # Build title keywords for client-side matching.
        # Include broad marketing/growth leadership terms so we capture
        # hiring managers, not just exact query matches.
        _extra_title_keywords = [
            "marketing", "growth", "demand gen", "demand generation",
            "digital marketing", "performance marketing", "paid media",
            "paid acquisition", "ppc", "sem", "cmo", "head of",
            "vp of marketing", "director of marketing", "brand",
        ]
        title_keywords = list({
            kw.lower()
            for kw in query.split() if len(kw) > 2
        } | {kw for kw in _extra_title_keywords})

        # Default to last 90 days if no since date
        if not since:
            from datetime import datetime, timedelta, timezone
            since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

        # Build API filters
        filters: dict[str, Any] = {"since": since}
        if technologies:
            filters["technologies"] = technologies
        if countries:
            filters["countries"] = countries

        matched_jobs: list[dict[str, Any]] = []
        offset = 0
        fetch_limit = min(limit * 5, 500)

        with httpx.Client(timeout=30.0) as client:
            while len(matched_jobs) < limit and offset < fetch_limit:
                batch_size = min(100, fetch_limit - offset)
                payload: dict[str, Any] = {
                    "filters": filters,
                    "limit": batch_size,
                    "offset": offset,
                }

                resp = self._post(client, "/jobs/find", payload)
                if resp is None:
                    break

                jobs = resp.get("jobs", [])
                total = resp.get("total", 0)
                credits_remaining = resp.get("credits_remaining", "?")

                logger.info(
                    f"Sumble jobs page: fetched {len(jobs)} (offset={offset}, "
                    f"total={total}), credits remaining: {credits_remaining}"
                )

                if not jobs:
                    break

                # Client-side filtering: title keywords + optional location
                for job in jobs:
                    if title_keywords:
                        title = (job.get("job_title") or "").lower()
                        if not any(kw in title for kw in title_keywords):
                            continue
                    if _location_kws:
                        loc = (job.get("location") or "").lower()
                        if not any(kw in loc for kw in _location_kws):
                            continue
                    matched_jobs.append(job)
                    if len(matched_jobs) >= limit:
                        break

                offset += len(jobs)
                if offset >= total:
                    break

                time.sleep(RATE_LIMIT_DELAY)

        logger.info(
            f"Sumble: found {len(matched_jobs)} matching jobs "
            f"(technologies={technologies}, query='{query}', scanned {offset})"
        )
        return matched_jobs

    # ------------------------------------------------------------------
    # Job-Related People (v5)
    # ------------------------------------------------------------------

    def find_related_people(
        self,
        job_id: int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find hiring managers and team members related to a job listing.

        Uses the v5 /jobs/find-related-people endpoint which returns people
        most relevant to the role — typically the hiring manager or team lead.
        1 credit per person returned.

        Args:
            job_id: Sumble job ID (from find_jobs results)
            limit:  Max people to return (default 5)

        Returns:
            List of person dicts with keys: id, name, job_title, job_function,
            job_level, linkedin_url, location, country, start_date
        """
        payload: dict[str, Any] = {
            "job_id": job_id,
            "limit": limit,
        }

        with httpx.Client(timeout=30.0) as client:
            resp = self._post(client, "/jobs/find-related-people", payload)
            if resp is None:
                return []

            people = resp.get("people", [])
            credits = resp.get("credits_remaining", "?")

            if people:
                logger.info(
                    "Sumble: found %d related people for job %d "
                    "(credits remaining: %s)",
                    len(people), job_id, credits,
                )
            return people

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------

    def find_contact(
        self,
        organization_domain: str | None = None,
        organization_id: int | None = None,
        job_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Find the best outreach contact at a company.

        Strategy (in order):
          1. If job_id provided, use find_related_people (v5) to get the
             hiring manager directly — most accurate, 1 credit/person.
          2. Search for marketing leadership (VP Marketing, CMO, Director
             of Growth) via people/find.
          3. Fall back to CEO/founder if no marketing leader found.

        Args:
            organization_domain: Company domain (e.g. "stripe.com")
            organization_id:     Sumble organization ID
            job_id:              Sumble job ID (enables related-people lookup)

        Returns:
            Person dict with keys: id, name, job_title, job_function,
            job_level, linkedin_url, url — or None if not found.
        """
        # Try job-related people first (hiring manager = best contact)
        if job_id is not None:
            related = self.find_related_people(job_id, limit=5)
            if related:
                # Prefer marketing/growth leaders among related people
                for person in related:
                    title = (person.get("job_title") or "").lower()
                    if any(kw in title for kw in [
                        "vp", "director", "head of", "cmo", "chief marketing",
                        "marketing", "growth", "demand",
                    ]):
                        logger.info(
                            "Found hiring manager via related-people: %s (%s) @ %s",
                            person.get("name"), person.get("job_title"),
                            organization_domain,
                        )
                        return person
                # Fall back to first related person
                first = related[0]
                logger.info(
                    "Using top related person: %s (%s) @ %s",
                    first.get("name"), first.get("job_title"),
                    organization_domain,
                )
                return first
        org: dict[str, Any]
        if organization_id is not None:
            org = {"id": organization_id}
        elif organization_domain:
            org = {"domain": organization_domain}
        else:
            return None

        # Priority-ordered searches: marketing leadership → executives
        searches = [
            {
                "label": "marketing leader",
                "filters": {
                    "job_functions": ["Marketing"],
                    "job_levels": ["VP", "Director", "CXO"],
                },
                "preferred_keywords": [
                    "vp marketing", "vp of marketing", "vice president marketing",
                    "cmo", "chief marketing", "head of marketing", "head of growth",
                    "director of marketing", "director of growth",
                    "director of demand", "director of digital",
                ],
            },
            {
                "label": "executive",
                "filters": {
                    "job_functions": ["Executive"],
                    "job_levels": [],
                },
                "preferred_keywords": [
                    "ceo", "chief executive", "founder", "co-founder",
                ],
            },
        ]

        with httpx.Client(timeout=30.0) as client:
            for search in searches:
                payload: dict[str, Any] = {
                    "organization": org,
                    "filters": search["filters"],
                    "limit": 10,
                    "offset": 0,
                }

                resp = self._post(client, "/people/find", payload)
                if resp is None:
                    continue

                people = resp.get("people", [])
                if not people:
                    continue

                # Prefer keyword-matched titles
                for person in people:
                    title = (person.get("job_title") or "").lower()
                    if any(kw in title for kw in search["preferred_keywords"]):
                        logger.info(
                            f"Found {search['label']}: {person.get('name')} "
                            f"({person.get('job_title')}) @ {organization_domain}"
                        )
                        return person

                # Fall back to first result from this search
                first = people[0]
                logger.info(
                    f"No exact title match, using top {search['label']}: "
                    f"{first.get('name')} ({first.get('job_title')}) "
                    f"@ {organization_domain}"
                )
                return first

        logger.debug(
            f"No contacts found for org domain={organization_domain} "
            f"id={organization_id}"
        )
        return None

    def find_ceo(
        self,
        organization_domain: str | None = None,
        organization_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Find the CEO/founder at a company. Delegates to find_contact."""
        return self.find_contact(
            organization_domain=organization_domain,
            organization_id=organization_id,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def check_account(self) -> dict[str, Any] | None:
        """Make a minimal API call to verify the account is working.

        Returns the response dict on success, or None if the account
        is rate-limited, out of credits, or has an invalid key.
        """
        payload: dict[str, Any] = {
            "filters": {"technologies": ["python"]},
            "limit": 1,
            "offset": 0,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = self._post(client, "/jobs/find", payload)
        return resp

    def _post(
        self,
        client: httpx.Client,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Make a POST request to the Sumble API with error handling."""
        url = f"{self.base_url}{path}"

        try:
            resp = client.post(url, headers=self._headers, json=payload)
        except httpx.TimeoutException:
            logger.error(f"Sumble timeout: {path}")
            return None

        if resp.status_code == 401:
            logger.error("Sumble: invalid or missing API key")
            return None
        if resp.status_code == 402:
            logger.error("Sumble: insufficient credits — stopping")
            return None
        if resp.status_code == 429:
            # Exponential backoff with jitter — keeps total wait under 60s
            waits = [5, 10, 20]
            for attempt, base_wait in enumerate(waits, 1):
                jitter = random.uniform(0, base_wait * 0.3)
                wait = base_wait + jitter
                logger.warning(
                    f"Sumble: rate limited, waiting {wait:.0f}s "
                    f"(attempt {attempt}/{len(waits)})..."
                )
                time.sleep(wait)
                try:
                    resp = client.post(url, headers=self._headers, json=payload)
                    if resp.status_code != 429:
                        break
                except Exception as e:
                    logger.error(f"Sumble retry {attempt} failed: {e}")
                    return None
            if resp.status_code == 429:
                logger.warning(
                    "Sumble: still rate limited after retries — skipping this run. "
                    "Will retry on next cron execution."
                )
                return None
            if resp.status_code != 200:
                logger.error(f"Sumble {path} returned {resp.status_code}: {resp.text[:300]}")
                return None
            return resp.json()

        if resp.status_code != 200:
            logger.error(f"Sumble {path} returned {resp.status_code}: {resp.text[:300]}")
            return None

        return resp.json()
