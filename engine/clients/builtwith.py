"""BuiltWith API client for tech stack and ad pixel detection.

Ported from apps/web/src/lib/builtwith.ts. Detects ad platform pixels,
CRM tools, analytics tools, and overall tech stack for a given domain.

API: https://api.builtwith.com/v21/api.json
Auth: API key as query parameter (BUILTWITH_API_KEY)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.builtwith.com/v21/api.json"
TIMEOUT = 10.0

# All ad platforms we track — used to compute "missing" platforms
ALL_AD_PLATFORMS = {"Google", "Meta", "LinkedIn", "X", "Reddit", "Microsoft", "TikTok", "Snapchat", "Pinterest"}

# Tech name → platform mapping (case-insensitive substring matching)
_PLATFORM_MAP: list[tuple[str, str]] = [
    ("google ads", "Google"),
    ("google tag manager", "Google"),
    ("google analytics", "Google"),
    ("facebook", "Meta"),
    ("meta pixel", "Meta"),
    ("linkedin", "LinkedIn"),
    ("twitter", "X"),
    ("x pixel", "X"),
    ("reddit", "Reddit"),
    ("microsoft", "Microsoft"),
    ("bing", "Microsoft"),
    ("tiktok", "TikTok"),
    ("snapchat", "Snapchat"),
    ("snap pixel", "Snapchat"),
    ("pinterest", "Pinterest"),
]

# CRM tool detection (substring match on tech name)
_CRM_KEYWORDS = [
    "hubspot", "salesforce", "zoho", "pipedrive", "freshsales",
    "close.io", "copper", "insightly", "sugar crm", "microsoft dynamics",
]

# Analytics tool detection
_ANALYTICS_KEYWORDS = [
    "google analytics", "mixpanel", "amplitude", "heap", "segment",
    "posthog", "matomo", "plausible", "hotjar", "fullstory",
    "clarity", "pendo",
]


def _normalize_domain(domain: str) -> str:
    d = re.sub(r"^https?://", "", domain)
    d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].lower()


class BuiltWithClient:
    """Detect ad pixels, CRM, analytics, and tech stack via BuiltWith API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.builtwith_api_key:
            raise ValueError("BUILTWITH_API_KEY is required")
        self._api_key = settings.builtwith_api_key

    def get_tech_profile(self, domain: str) -> dict[str, Any] | None:
        """Fetch full technology profile for a domain.

        Returns dict with keys:
            ad_platforms:   list of detected ad platform names (e.g. ["Google", "Meta"])
            missing_platforms: list of ad platforms NOT detected
            technologies:   list of all technology names
            crm_tool:       detected CRM tool name or ""
            analytics_tool: detected analytics tool name or ""
            tech_stack:     top 5 technology names as comma-separated string
            pixel_count:    number of ad platforms detected
        """
        d = _normalize_domain(domain)
        url = f"{BASE_URL}?KEY={self._api_key}&LOOKUP={d}"

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.get(url)

            if resp.status_code != 200:
                logger.warning(f"[BuiltWith] {d} returned {resp.status_code}")
                return None

            data = resp.json()
        except httpx.TimeoutException:
            logger.error(f"[BuiltWith] Timeout for {d}")
            return None
        except Exception as exc:
            logger.error(f"[BuiltWith] Request error for {d}: {exc}")
            return None

        results = data.get("Results") or []
        if not results:
            logger.info(f"[BuiltWith] No results for {d}")
            return None

        paths = results[0].get("Result", {}).get("Paths") or []
        if not paths:
            logger.info(f"[BuiltWith] No paths for {d}")
            return None

        technologies = paths[0].get("Technologies") or []
        tech_names = [t.get("Name", "") for t in technologies]

        # Detect ad platforms
        ad_platforms: set[str] = set()
        for tech in technologies:
            name_lower = tech.get("Name", "").lower()
            for keyword, platform in _PLATFORM_MAP:
                if keyword in name_lower:
                    ad_platforms.add(platform)

        # Detect CRM
        crm_tool = ""
        for tech_name in tech_names:
            name_lower = tech_name.lower()
            for kw in _CRM_KEYWORDS:
                if kw in name_lower:
                    crm_tool = tech_name
                    break
            if crm_tool:
                break

        # Detect analytics
        analytics_tool = ""
        for tech_name in tech_names:
            name_lower = tech_name.lower()
            for kw in _ANALYTICS_KEYWORDS:
                if kw in name_lower:
                    analytics_tool = tech_name
                    break
            if analytics_tool:
                break

        missing = sorted(ALL_AD_PLATFORMS - ad_platforms)
        installed = sorted(ad_platforms)

        # Top tech stack (deduplicated, skip very generic names)
        top_tech = []
        seen = set()
        for name in tech_names:
            if name.lower() not in seen and len(name) > 2:
                seen.add(name.lower())
                top_tech.append(name)
            if len(top_tech) >= 5:
                break

        logger.info(
            f"[BuiltWith] {d}: {len(installed)} ad platforms, "
            f"{len(tech_names)} technologies, CRM={crm_tool or 'none'}"
        )

        return {
            "domain": d,
            "ad_platforms": installed,
            "missing_platforms": missing,
            "technologies": tech_names,
            "crm_tool": crm_tool,
            "analytics_tool": analytics_tool,
            "tech_stack": ", ".join(top_tech),
            "pixel_count": len(installed),
        }
