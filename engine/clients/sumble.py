"""Sumble.com v3 API client — Jobs + People endpoints.

API docs: https://docs.sumble.com/api
Base URL: https://api.sumble.com/v3
Auth:     Bearer token in Authorization header
Rate:     10 requests/second

Credit costs:
  - Jobs find:   3 credits per job returned
  - People find: 1 credit per person returned
"""

from __future__ import annotations

import logging
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
        # Build title keywords for optional client-side matching
        title_keywords = [kw.lower() for kw in query.split() if len(kw) > 2]

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

                # If title keywords provided, filter client-side;
                # otherwise accept all technology-matched jobs
                for job in jobs:
                    if title_keywords:
                        title = (job.get("job_title") or "").lower()
                        if not any(kw in title for kw in title_keywords):
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
    # People
    # ------------------------------------------------------------------

    def find_ceo(
        self,
        organization_domain: str | None = None,
        organization_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Find the CEO/founder at a company.

        Searches for C-suite / Executive level people and picks the
        most likely CEO from the results.

        Args:
            organization_domain: Company domain (e.g. "stripe.com")
            organization_id:     Sumble organization ID

        Returns:
            Person dict with keys: id, name, job_title, job_function,
            job_level, linkedin_url, url — or None if not found.
        """
        # Build organization identifier
        org: dict[str, Any]
        if organization_id is not None:
            org = {"id": organization_id}
        elif organization_domain:
            org = {"domain": organization_domain}
        else:
            return None

        payload: dict[str, Any] = {
            "organization": org,
            "filters": {
                "job_functions": ["Executive"],
                "job_levels": [],
            },
            "limit": 10,
            "offset": 0,
        }

        with httpx.Client(timeout=30.0) as client:
            resp = self._post(client, "/people/find", payload)

        if resp is None:
            return None

        people = resp.get("people", [])
        if not people:
            logger.debug(
                f"No executives found for org domain={organization_domain} "
                f"id={organization_id}"
            )
            return None

        # Prefer CEO/Founder titles, then fall back to first executive
        ceo_keywords = ["ceo", "chief executive", "founder", "co-founder"]
        for person in people:
            title = (person.get("job_title") or "").lower()
            if any(kw in title for kw in ceo_keywords):
                logger.info(
                    f"Found CEO: {person.get('name')} ({person.get('job_title')}) "
                    f"@ {organization_domain}"
                )
                return person

        # Fall back to first executive result
        first = people[0]
        logger.info(
            f"No CEO title match, using top executive: {first.get('name')} "
            f"({first.get('job_title')}) @ {organization_domain}"
        )
        return first

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
            # Exponential backoff — account-level rate limits may need
            # much longer waits than transient burst limits.
            waits = [10, 30, 60, 120]
            for attempt, wait in enumerate(waits, 1):
                logger.warning(
                    f"Sumble: rate limited, waiting {wait}s "
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
                logger.error(
                    "Sumble: still rate limited after retries. "
                    "Check your account at https://sumble.com/account/api-keys — "
                    "you may need to wait or upgrade your plan."
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
