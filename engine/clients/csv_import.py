"""Import leads from CSV files exported from Sumble's web UI.

This bypasses the Sumble API entirely — useful when:
  - API rate limits are hit (persistent 429s on free tier)
  - You want to use Sumble's free web exports (no credit cost)
  - You have leads from other sources (Apollo, LinkedIn, etc.)

Expected CSV columns (flexible matching):
  Jobs:   job_title, organization_name, organization_domain, url, location, ...
  People: name, job_title, linkedin_url, organization_name, organization_domain, ...

Usage:
  run-engine --csv data/sumble-export.csv --dry-run
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Column name aliases for flexible CSV matching
_JOB_TITLE_COLS = {"job_title", "title", "job title", "role", "position"}
_ORG_NAME_COLS = {"organization_name", "company_name", "company", "org_name", "organization"}
_ORG_DOMAIN_COLS = {"organization_domain", "company_domain", "domain", "website"}
_LOCATION_COLS = {"location", "city", "country", "region"}
_JOB_URL_COLS = {"job_url", "url", "link", "posting_url", "job_link"}
_PERSON_NAME_COLS = {"name", "full_name", "contact_name", "person_name"}
_PERSON_TITLE_COLS = {"job_title", "title", "role", "position"}
_LINKEDIN_COLS = {"linkedin_url", "linkedin", "linkedin_profile", "profile_url"}


def _find_column(headers: list[str], candidates: set[str]) -> str | None:
    """Find the first matching column name (case-insensitive)."""
    header_lower = {h.lower().strip(): h for h in headers}
    for candidate in candidates:
        if candidate in header_lower:
            return header_lower[candidate]
    return None


def load_jobs_csv(
    csv_path: str | Path,
    title_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load job postings from a CSV file.

    Args:
        csv_path:        Path to the CSV file.
        title_keywords:  Optional keywords to filter by job title (any match).

    Returns:
        List of job dicts compatible with the pipeline's expected format.
    """
    path = Path(csv_path)
    if not path.exists():
        logger.error(f"CSV file not found: {path}")
        return []

    jobs: list[dict[str, Any]] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Map columns
        col_title = _find_column(headers, _JOB_TITLE_COLS)
        col_org = _find_column(headers, _ORG_NAME_COLS)
        col_domain = _find_column(headers, _ORG_DOMAIN_COLS)
        col_location = _find_column(headers, _LOCATION_COLS)
        col_url = _find_column(headers, _JOB_URL_COLS)

        if not col_title:
            logger.error(f"CSV missing job title column. Headers: {headers}")
            return []
        if not col_org:
            logger.error(f"CSV missing organization name column. Headers: {headers}")
            return []

        logger.info(
            f"CSV column mapping: title={col_title}, org={col_org}, "
            f"domain={col_domain}, location={col_location}, url={col_url}"
        )

        for i, row in enumerate(reader):
            job_title = (row.get(col_title) or "").strip()
            if not job_title:
                continue

            # Optional title filtering
            if title_keywords:
                title_lower = job_title.lower()
                if not any(kw.lower() in title_lower for kw in title_keywords):
                    continue

            org_name = (row.get(col_org) or "").strip()
            org_domain = (row.get(col_domain) or "").strip() if col_domain else ""
            location = (row.get(col_location) or "").strip() if col_location else ""
            url = (row.get(col_url) or "").strip() if col_url else ""

            # Clean domain (remove protocol if present)
            if org_domain.startswith(("http://", "https://")):
                org_domain = org_domain.split("//", 1)[1].split("/")[0]

            jobs.append({
                "id": f"csv-{i}-{org_domain or org_name}",
                "organization_name": org_name,
                "organization_domain": org_domain or None,
                "organization_id": None,
                "job_title": job_title,
                "url": url,
                "location": location,
                "datetime_pulled": "",
            })

    logger.info(f"Loaded {len(jobs)} jobs from {path}")
    return jobs


def load_contacts_csv(csv_path: str | Path) -> list[dict[str, Any]]:
    """Load pre-enriched contacts from a CSV file.

    Use when you already have CEO/founder contacts (e.g., from Apollo
    or manual research). Skips the Sumble People API enrichment step.

    Returns:
        List of dicts with keys: name, job_title, linkedin_url,
        organization_name, organization_domain.
    """
    path = Path(csv_path)
    if not path.exists():
        logger.error(f"CSV file not found: {path}")
        return []

    contacts: list[dict[str, Any]] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        col_name = _find_column(headers, _PERSON_NAME_COLS)
        col_title = _find_column(headers, _PERSON_TITLE_COLS)
        col_linkedin = _find_column(headers, _LINKEDIN_COLS)
        col_org = _find_column(headers, _ORG_NAME_COLS)
        col_domain = _find_column(headers, _ORG_DOMAIN_COLS)

        if not col_name:
            logger.error(f"CSV missing person name column. Headers: {headers}")
            return []

        for row in reader:
            name = (row.get(col_name) or "").strip()
            if not name:
                continue

            contacts.append({
                "name": name,
                "job_title": (row.get(col_title) or "").strip() if col_title else "",
                "linkedin_url": (row.get(col_linkedin) or "").strip() if col_linkedin else "",
                "organization_name": (row.get(col_org) or "").strip() if col_org else "",
                "organization_domain": (row.get(col_domain) or "").strip() if col_domain else "",
            })

    logger.info(f"Loaded {len(contacts)} contacts from {path}")
    return contacts
