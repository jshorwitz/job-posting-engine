"""Fundraising signal discovery via Serper (Google News).

Finds companies that recently raised funding rounds and routes them
into the outreach pipeline. Companies raising money need to deploy
capital into growth channels — perfect timing for Synter.

Usage:
    from engine.signals.fundraising import discover_funded_companies
    results = discover_funded_companies(settings, session)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/news"

# Queries that surface recent funding rounds for marketing/ad-tech adjacent companies
FUNDING_QUERIES = [
    # Direct-to-consumer / ecommerce (run lots of ads)
    "DTC brand raises funding 2026",
    "ecommerce startup raised series A 2026",
    "D2C company funding round 2026",
    "consumer brand raised seed round 2026",
    # SaaS with growth focus
    "SaaS startup raises series A growth 2026",
    "B2B SaaS funding round 2026",
    "martech startup raised funding 2026",
    "ad tech startup raised 2026",
    # Specific funding stages our ICP fits
    "raised series A million 2026",
    "raised series B million 2026",
    "raised seed round million 2026",
    "startup raises $5M",
    "startup raises $10M",
    "startup raises $15M",
    "startup raises $20M",
    # Marketing/agency adjacent
    "marketing agency acquired 2026",
    "digital agency raises funding 2026",
    "performance marketing startup funding",
]


def discover_funded_companies(
    settings: Settings,
    *,
    max_results: int = 50,
    days_back: int = 14,
) -> list[dict[str, Any]]:
    """Discover companies that recently raised funding via Google News.

    Returns list of dicts with: company_name, domain, funding_amount,
    funding_round, news_url, news_title, published_date.
    """
    if not settings.serper_api_key:
        logger.warning("[Fundraising] SERPER_API_KEY not set")
        return []

    results: list[dict[str, Any]] = []
    seen_domains: set[str] = set()

    for query in FUNDING_QUERIES:
        if len(results) >= max_results:
            break

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    SERPER_URL,
                    headers={"X-API-KEY": settings.serper_api_key},
                    json={
                        "q": query,
                        "num": 20,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"[Fundraising] Serper HTTP {resp.status_code}")
                    continue

                data = resp.json()
                news_items = data.get("news", [])

                for item in news_items:
                    parsed = _parse_funding_news(item)
                    if not parsed:
                        continue
                    # Dedup by company name (domain isn't known yet)
                    dedup_key = (parsed.get("company_name") or parsed.get("news_title", "")).lower().strip()
                    if dedup_key and dedup_key not in seen_domains:
                        seen_domains.add(dedup_key)
                        results.append(parsed)

        except Exception as exc:
            logger.warning(f"[Fundraising] Error querying '{query}': {exc}")
            continue

    # Enrich with domains — use Firecrawl to scrape each article and extract company website
    if settings.firecrawl_api_key:
        logger.info(f"[Fundraising] Enriching {len(results)} results with company domains via Firecrawl...")
        for r in results:
            if r.get("domain"):
                continue
            company_name = r.get("company_name", "")
            if not company_name:
                continue
            # Quick Google search for company domain
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(
                        "https://google.serper.dev/search",
                        headers={"X-API-KEY": settings.serper_api_key},
                        json={"q": f"{company_name} official website", "num": 3},
                    )
                    if resp.status_code == 200:
                        organic = resp.json().get("organic", [])
                        for result_item in organic:
                            link = result_item.get("link", "")
                            if link:
                                from urllib.parse import urlparse
                                parsed_url = urlparse(link)
                                candidate = parsed_url.netloc.replace("www.", "")
                                # Skip common non-company domains
                                skip = ["crunchbase.com", "linkedin.com", "twitter.com",
                                        "techcrunch.com", "bloomberg.com", "reuters.com",
                                        "wikipedia.org", "pitchbook.com", "google.com",
                                        "facebook.com", "youtube.com"]
                                if candidate and not any(s in candidate for s in skip):
                                    r["domain"] = candidate
                                    r["company_domain"] = candidate
                                    logger.info(f"[Fundraising] Found domain for {company_name}: {candidate}")
                                    break
            except Exception:
                pass

    logger.info(f"[Fundraising] Discovered {len(results)} funded companies")
    return results


def _parse_funding_news(item: dict) -> dict[str, Any] | None:
    """Extract company info from a news article about funding."""
    title = item.get("title", "")
    snippet = item.get("snippet", "")
    link = item.get("link", "")
    date = item.get("date", "")
    source = item.get("source", "")

    # The news link is the publisher domain, not the funded company
    # We need to extract the company domain from the title/snippet instead
    domain = ""

    # Try to extract company name from title
    # Common patterns: "CompanyName Raises $XM in Series A"
    company_name = ""
    funding_amount = ""
    funding_round = ""

    # Pattern: "Company raises/raised $XM"
    amount_match = re.search(r'\$(\d+(?:\.\d+)?)\s*([MBK])', title + " " + snippet, re.IGNORECASE)
    if amount_match:
        funding_amount = f"${amount_match.group(1)}{amount_match.group(2).upper()}"

    # Pattern: "Series A/B/C" or "Seed" or "Pre-Seed"
    round_match = re.search(r'(Series\s+[A-F]|Seed|Pre-Seed|Growth)', title + " " + snippet, re.IGNORECASE)
    if round_match:
        funding_round = round_match.group(1)

    # Extract company name from title using multiple strategies
    funding_verbs = r'(?:raises?|raised|secures?|secured|closes?|closed|announces?|lands?|landed|nabs?|gets?|bags?|receives?|received|completes?|completed|snags?|grabs?|nets?|pulls?)'

    # Strategy 1: "CompanyName raises $XM..."
    name_match = re.match(rf'^(.+?)\s+{funding_verbs}\s', title, re.IGNORECASE)
    if name_match:
        company_name = name_match.group(1).strip()

    # Strategy 2: "Exclusive: CompanyName raises..."
    if not company_name:
        colon_match = re.search(rf':\s*(.+?)\s+{funding_verbs}\s', title, re.IGNORECASE)
        if colon_match:
            company_name = colon_match.group(1).strip()

    # Strategy 3: "City startup CompanyName raises..."
    if not company_name:
        startup_match = re.search(rf'startup\s+(.+?)\s+{funding_verbs}\s', title, re.IGNORECASE)
        if startup_match:
            company_name = startup_match.group(1).strip()

    # Clean up common prefixes/suffixes from company name
    if company_name:
        # Remove location prefixes like "Birmingham communications startup"
        company_name = re.sub(r'^(?:[\w\-]+\s+){0,2}(?:startup|company|firm|platform|healthtech|fintech|AI)\s+', '', company_name, flags=re.IGNORECASE).strip()
        # Remove trailing descriptors
        company_name = re.sub(r',?\s+(?:a|an|the|which|that|inc|ltd|co)\.?\s*$', '', company_name, flags=re.IGNORECASE).strip()
        # If still too long (> 8 words), trim to likely company name (first 3 words)
        words = company_name.split()
        if len(words) > 8:
            company_name = " ".join(words[:3])

    # Accept if we have a funding amount (even without clean company name)
    if not company_name and not funding_amount:
        return None

    return {
        "company_name": company_name,
        "domain": domain,
        "funding_amount": funding_amount,
        "funding_round": funding_round,
        "news_url": link,
        "news_title": title,
        "news_snippet": snippet[:300],
        "published_date": date,
        "source": source,
        "signal_type": "fundraising",
    }
