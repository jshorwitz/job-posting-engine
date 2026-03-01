"""Firecrawl API client for homepage headline extraction.

Ported from apps/web/src/lib/firecrawl.ts. Scrapes a domain's homepage
to extract the main H1/heading and key content for email personalization.

API: https://api.firecrawl.dev/v0/scrape (POST)
Auth: Bearer token (FIRECRAWL_API_KEY)
"""

from __future__ import annotations

import logging
import re

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

SCRAPE_URL = "https://api.firecrawl.dev/v0/scrape"
TIMEOUT = 15.0


class FirecrawlClient:
    """Scrape homepage to extract H1 headline and key content."""

    def __init__(self, settings: Settings) -> None:
        if not settings.firecrawl_api_key:
            raise ValueError("FIRECRAWL_API_KEY is required")
        self._api_key = settings.firecrawl_api_key

    def get_headline(self, domain: str) -> dict[str, str] | None:
        """Scrape a domain's homepage and extract the main headline.

        Returns dict with keys:
            headline:    Main H1 text (or og:title fallback)
            description: Meta description or first content paragraph
            title:       Page title
        or None on failure.
        """
        url = domain if domain.startswith("http") else f"https://{domain}"

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(
                    SCRAPE_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "url": url,
                        "pageOptions": {
                            "onlyMainContent": True,
                            "includeHtml": False,
                        },
                        "timeout": 12000,
                    },
                )

            if resp.status_code != 200:
                logger.warning(f"[Firecrawl] {domain} returned {resp.status_code}")
                return None

            data = resp.json()
        except httpx.TimeoutException:
            logger.error(f"[Firecrawl] Timeout for {domain}")
            return None
        except Exception as exc:
            logger.error(f"[Firecrawl] Request error for {domain}: {exc}")
            return None

        if not data.get("success") or not data.get("data"):
            logger.info(f"[Firecrawl] No data for {domain}")
            return None

        payload = data["data"]
        markdown = payload.get("markdown", "")
        metadata = payload.get("metadata") or {}

        # Extract first H1 from markdown
        headline = ""
        for line in markdown.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                headline = re.sub(r"^#+\s*", "", stripped).strip()
                break

        # Fallback to og:title or page title
        if not headline:
            headline = metadata.get("ogTitle") or metadata.get("title") or ""

        # Extract description
        description = metadata.get("description") or metadata.get("ogDescription") or ""

        # If no description, grab first substantial paragraph from markdown
        if not description:
            for line in markdown.split("\n"):
                stripped = line.strip()
                if not stripped.startswith("#") and len(stripped) > 60:
                    description = stripped[:200]
                    break

        title = metadata.get("title") or ""

        # Truncate for Instantly/Loops compatibility
        headline = headline[:200] if headline else ""
        description = description[:300] if description else ""

        if headline:
            logger.info(f"[Firecrawl] {domain}: \"{headline[:60]}...\"")
        else:
            logger.info(f"[Firecrawl] {domain}: no headline found")

        return {
            "headline": headline,
            "description": description,
            "title": title,
        }
