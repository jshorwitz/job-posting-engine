"""Tech stack change signal discovery via BuiltWith.

Finds companies that recently installed ad platform pixels (Google Ads,
Meta Pixel, LinkedIn Insight Tag, etc.). Companies starting to run ads
for the first time are prime Synter prospects.

Usage:
    from engine.signals.tech_changes import discover_new_advertisers
    results = discover_new_advertisers(settings)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

BUILTWITH_TRENDS_URL = "https://api.builtwith.com/trends/v6/api.json"

# Technologies that indicate a company is starting to run ads
AD_TECHNOLOGIES = [
    "Google Ads",
    "Google Ads Conversion Tracking",
    "Facebook Pixel",
    "Meta Pixel",
    "LinkedIn Insight Tag",
    "TikTok Pixel",
    "Reddit Pixel",
    "Twitter Ads",
    "Microsoft Advertising",
    "Pinterest Tag",
    "Snapchat Pixel",
]


def discover_new_advertisers(
    settings: Settings,
    *,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Find companies that recently installed ad pixels via BuiltWith Trends.

    Returns list of domains that recently added advertising technology.
    """
    if not settings.builtwith_api_key:
        logger.warning("[TechChanges] BUILTWITH_API_KEY not set")
        return []

    results: list[dict[str, Any]] = []
    seen_domains: set[str] = set()

    for tech in AD_TECHNOLOGIES:
        if len(results) >= max_results:
            break

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    BUILTWITH_TRENDS_URL,
                    params={
                        "KEY": settings.builtwith_api_key,
                        "TECH": tech,
                        "DATE": "latest",
                    },
                )

                if resp.status_code != 200:
                    logger.warning(f"[TechChanges] BuiltWith HTTP {resp.status_code} for {tech}")
                    continue

                data = resp.json()
                # BuiltWith Trends returns domains using this tech
                domains = data.get("Domains", [])

                for domain_entry in domains[:20]:  # Top 20 per tech
                    domain = domain_entry if isinstance(domain_entry, str) else domain_entry.get("Domain", "")
                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)
                        results.append({
                            "domain": domain,
                            "technology_added": tech,
                            "signal_type": "tech_change",
                        })

        except Exception as exc:
            logger.warning(f"[TechChanges] Error querying {tech}: {exc}")
            continue

    logger.info(f"[TechChanges] Discovered {len(results)} new advertisers")
    return results


def discover_multi_platform_advertisers(
    settings: Settings,
    domains: list[str],
) -> list[dict[str, Any]]:
    """Check which domains run ads on 2+ platforms via BuiltWith.

    Takes a list of domains and returns those running multi-platform ads.
    Uses the standard BuiltWith API (not Trends).
    """
    from engine.clients.builtwith import get_tech_profile

    results: list[dict[str, Any]] = []

    for domain in domains:
        try:
            profile = get_tech_profile(settings, domain)
            if not profile:
                continue

            platforms = profile.get("ad_platforms", [])
            if len(platforms) >= 2:
                results.append({
                    "domain": domain,
                    "ad_platforms": platforms,
                    "platform_count": len(platforms),
                    "crm": profile.get("crm", []),
                    "analytics": profile.get("analytics", []),
                    "signal_type": "multi_platform_advertiser",
                })

        except Exception as exc:
            logger.warning(f"[TechChanges] Error checking {domain}: {exc}")
            continue

    logger.info(f"[TechChanges] Found {len(results)} multi-platform advertisers from {len(domains)} domains")
    return results
