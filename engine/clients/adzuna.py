"""Adzuna Job Search API client.

Free tier: 250 requests/day.
Docs: https://developer.adzuna.com/docs/search
Sign up: https://developer.adzuna.com/

Returns jobs from Indeed, LinkedIn, Glassdoor, and thousands of other boards
aggregated into a single API.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs"
RATE_LIMIT_DELAY = 0.25  # stay under rate limits


class AdzunaClient:
    """Thin wrapper around the Adzuna v1 job search API."""

    def __init__(self, settings: Settings) -> None:
        self.app_id = settings.adzuna_app_id
        self.app_key = settings.adzuna_api_key

    def find_jobs(
        self,
        query: str = "growth marketing",
        country: str = "us",
        limit: int = 50,
        title_only: bool = False,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for job postings matching a query.

        Args:
            query:      Search terms (e.g. "head of growth", "performance marketing").
            country:    ISO country code (default: "us").
            limit:      Max results to return.
            title_only: If True, search only job titles (not descriptions).
            where:      Location filter (e.g. "Portland, OR", "Seattle").
                        Adzuna matches against job location text.

        Returns:
            List of normalised job dicts compatible with the pipeline:
                id, organization_name, organization_domain, job_title,
                url, location, datetime_pulled, organization_id
        """
        matched: list[dict[str, Any]] = []
        page = 1
        per_page = min(limit, 50)  # Adzuna max per page is 50

        with httpx.Client(timeout=30.0) as client:
            while len(matched) < limit:
                params: dict[str, Any] = {
                    "app_id": self.app_id,
                    "app_key": self.app_key,
                    "results_per_page": per_page,
                    "content-type": "application/json",
                    "sort_by": "date",
                }

                if title_only:
                    params["what_and"] = query
                    params["title_only"] = query
                else:
                    params["what"] = query

                if where:
                    params["where"] = where

                url = f"{BASE_URL}/{country}/search/{page}"

                try:
                    resp = client.get(url, params=params)
                except httpx.TimeoutException:
                    logger.error("Adzuna: timeout")
                    break

                if resp.status_code == 401:
                    logger.error("Adzuna: invalid API credentials")
                    break
                if resp.status_code == 429:
                    logger.warning("Adzuna: rate limited — stopping")
                    break
                if resp.status_code != 200:
                    logger.error(f"Adzuna: {resp.status_code} — {resp.text[:200]}")
                    break

                data = resp.json()
                results = data.get("results", [])

                if not results:
                    break

                for job in results:
                    normalised = _normalise(job)
                    if normalised:
                        matched.append(normalised)
                        if len(matched) >= limit:
                            break

                total = data.get("count", 0)
                logger.info(
                    f"Adzuna page {page}: {len(results)} results "
                    f"(total={total}, matched={len(matched)})"
                )

                if page * per_page >= total:
                    break

                page += 1
                time.sleep(RATE_LIMIT_DELAY)

        logger.info(f"Adzuna: found {len(matched)} jobs for query '{query}'")
        return matched


def _normalise(job: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an Adzuna job result to the pipeline's expected format."""
    title = job.get("title", "")
    company = job.get("company", {})
    company_name = company.get("display_name", "") if isinstance(company, dict) else ""

    if not company_name or not title:
        return None

    # Extract domain from redirect URL if possible
    redirect = job.get("redirect_url", "")

    location_obj = job.get("location", {})
    location = ""
    if isinstance(location_obj, dict):
        location = location_obj.get("display_name", "")

    return {
        "id": f"adzuna-{job.get('id', '')}",
        "organization_name": _clean_html(company_name),
        "organization_domain": None,  # Adzuna doesn't provide domains
        "organization_id": None,
        "job_title": _clean_html(title),
        "url": redirect,
        "location": location,
        "datetime_pulled": job.get("created", ""),
    }


def _clean_html(text: str) -> str:
    """Strip basic HTML tags from Adzuna responses (they bold search terms)."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()
