"""Hunter.io API client for email enrichment.

Uses the Email Finder endpoint to resolve a person's work email
from their name + company domain.

API docs: https://hunter.io/api-documentation/v2
Rate limits: 15 req/s, 500 req/min
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hunter.io/v2"
RATE_LIMIT_DELAY = 0.1  # stay under 15 req/s


class HunterClient:
    """Find and verify email addresses via Hunter.io."""

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.hunter_api_key
        if not self.api_key:
            raise ValueError("HUNTER_API_KEY is required")

    def find_email(
        self,
        domain: str,
        full_name: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Find the most likely email address for a person at a company.

        Args:
            domain:     Company domain (e.g. "stripe.com").
            full_name:  Person's full name (used if first/last not provided).
            first_name: Person's first name (optional, extracted from full_name).
            last_name:  Person's last name (optional, extracted from full_name).

        Returns:
            Dict with keys: email, score, position, company, verification
            or None if not found.
        """
        if not first_name or not last_name:
            parts = full_name.strip().split()
            if len(parts) < 2:
                logger.warning(f"Cannot split name into first/last: {full_name!r}")
                return None
            first_name = parts[0]
            last_name = " ".join(parts[1:])

        params = {
            "domain": domain,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": self.api_key,
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{BASE_URL}/email-finder", params=params)

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                email = data.get("email")
                score = data.get("score", 0)

                if email and score >= 30:
                    logger.info(
                        f"Hunter: found {email} for {full_name} @ {domain} "
                        f"(score={score})"
                    )
                    return data
                else:
                    logger.info(
                        f"Hunter: low confidence for {full_name} @ {domain} "
                        f"(email={email}, score={score})"
                    )
                    return None

            if resp.status_code == 404:
                logger.info(f"Hunter: no email found for {full_name} @ {domain}")
                return None

            if resp.status_code == 429:
                logger.warning("Hunter: rate limited, waiting 5s...")
                time.sleep(5)
                return None

            logger.error(
                f"Hunter email-finder returned {resp.status_code}: "
                f"{resp.text[:200]}"
            )
            return None

        except httpx.TimeoutException:
            logger.error(f"Hunter timeout for {full_name} @ {domain}")
            return None

    def find_domain(self, company_name: str) -> str | None:
        """Resolve a company name to its domain using Hunter's Domain Search.

        Uses the `company` parameter of the domain-search endpoint, which
        accepts a company name and returns the associated domain + emails.
        This is free (1 search credit per call).

        Args:
            company_name: Company name (e.g. "Stripe", "Intercom").

        Returns:
            Domain string (e.g. "stripe.com") or None if not found.
        """
        if not company_name or len(company_name.strip()) < 2:
            return None

        params = {
            "company": company_name.strip(),
            "limit": 1,
            "api_key": self.api_key,
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{BASE_URL}/domain-search", params=params)

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                domain = data.get("domain")
                if domain:
                    logger.info(f"Hunter: resolved '{company_name}' → {domain}")
                    return domain
                logger.debug(f"Hunter: no domain found for '{company_name}'")
                return None

            if resp.status_code == 429:
                logger.warning("Hunter: rate limited on domain search")
                time.sleep(5)
                return None

            logger.debug(
                f"Hunter domain-search returned {resp.status_code} for '{company_name}'"
            )
            return None

        except httpx.TimeoutException:
            logger.error(f"Hunter timeout resolving domain for '{company_name}'")
            return None

    def verify_email(self, email: str) -> dict[str, Any] | None:
        """Verify an email address deliverability.

        Returns:
            Dict with keys: status, score, email, smtp_check, etc.
            or None on error.
        """
        params = {"email": email, "api_key": self.api_key}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{BASE_URL}/email-verifier", params=params)

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                status = data.get("status", "unknown")
                score = data.get("score", 0)
                logger.info(f"Hunter verify: {email} → {status} (score={score})")
                return data

            logger.error(f"Hunter verify returned {resp.status_code}: {resp.text[:200]}")
            return None

        except httpx.TimeoutException:
            logger.error(f"Hunter verify timeout for {email}")
            return None

    def check_account(self) -> dict[str, Any] | None:
        """Check Hunter.io account status and remaining requests."""
        params = {"api_key": self.api_key}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{BASE_URL}/account", params=params)

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                requests_info = data.get("requests", {})
                searches = requests_info.get("searches", {})
                logger.info(
                    f"Hunter account: "
                    f"{searches.get('used', '?')}/{searches.get('available', '?')} "
                    f"searches used"
                )
                return data

            logger.error(f"Hunter account check failed: {resp.status_code}")
            return None

        except httpx.TimeoutException:
            logger.error("Hunter account check timed out")
            return None
