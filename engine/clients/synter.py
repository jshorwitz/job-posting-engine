"""Synter MCP client — SimilarWeb domain analysis + media plan generation.

Uses the Synter API (same backend as the MCP tools) to fetch SimilarWeb
traffic data and generate personalized media plan proposals for outreach.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

SYNTER_BASE_URL = "https://api.syntermedia.ai/v1"


class SynterClient:
    """Client for Synter's SimilarWeb analysis and media plan generation."""

    def __init__(self, settings: Settings) -> None:
        if not settings.synter_api_key:
            raise ValueError("SYNTER_API_KEY is required")
        self._api_key = settings.synter_api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def analyze_domain(self, domain: str) -> dict[str, Any] | None:
        """Fetch SimilarWeb traffic analysis for a domain via Synter.

        Returns dict with visits, bounce_rate, traffic_sources, device_split,
        paid_search_pct, etc. Returns None on failure.
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{SYNTER_BASE_URL}/execute",
                    headers=self._headers,
                    json={
                        "action": "similarweb_analyze_domain",
                        "args": ["--domain", domain],
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"[Synter] HTTP {resp.status_code} for {domain}")
                    return None

                data = resp.json()
                if not data.get("success", False):
                    logger.info(f"[Synter] No data for {domain}")
                    return None

                return self._parse_analysis(data, domain)

        except Exception as exc:
            logger.warning(f"[Synter] Domain analysis failed for {domain}: {exc}")
            return None

    def _parse_analysis(self, raw: dict[str, Any], domain: str) -> dict[str, Any]:
        """Extract key metrics from raw SimilarWeb response."""
        result: dict[str, Any] = {"domain": domain}

        # Monthly visits (latest month)
        visits_data = raw.get("visits", {}).get("visits", [])
        if visits_data:
            result["monthly_visits"] = int(visits_data[-1].get("visits", 0))
        else:
            result["monthly_visits"] = 0

        # Bounce rate (latest month)
        bounce_data = raw.get("bounce_rate", {}).get("bounce_rate", [])
        if bounce_data:
            result["bounce_rate"] = round(bounce_data[-1].get("bounce_rate", 0) * 100, 1)

        # Pages per visit
        ppv_data = raw.get("pages_per_visit", {}).get("pages_per_visit", [])
        if ppv_data:
            result["pages_per_visit"] = round(ppv_data[-1].get("pages_per_visit", 0), 1)

        # Avg visit duration
        dur_data = raw.get("avg_visit_duration", {}).get("average_visit_duration", [])
        if dur_data:
            result["avg_visit_duration_sec"] = round(dur_data[-1].get("average_visit_duration", 0))

        # Device split
        device = raw.get("device_split", {})
        result["desktop_pct"] = round(device.get("desktop_visit_share", 0) * 100, 1)
        result["mobile_pct"] = round(device.get("mobile_web_visit_share", 0) * 100, 1)

        # Traffic sources
        sources = raw.get("traffic_sources", {}).get("overview", [])
        result["traffic_sources"] = sources

        # Extract paid search percentage
        paid_pct = 0.0
        organic_pct = 0.0
        direct_pct = 0.0
        social_pct = 0.0
        for src in sources:
            share = src.get("share", 0) * 100
            stype = src.get("source_type", "")
            if "Paid" in stype:
                paid_pct += share
            elif "Organic" in stype:
                organic_pct += share
            elif stype == "Direct":
                direct_pct += share
            elif stype == "Social":
                social_pct += share

        result["paid_search_pct"] = round(paid_pct, 2)
        result["organic_search_pct"] = round(organic_pct, 2)
        result["direct_pct"] = round(direct_pct, 2)
        result["social_pct"] = round(social_pct, 2)

        # Global rank
        rank_data = raw.get("global_rank", {}).get("global_rank", [])
        if rank_data:
            result["global_rank"] = rank_data[-1].get("global_rank", 0)

        return result


def generate_media_plan(analysis: dict[str, Any], company_name: str) -> dict[str, Any]:
    """Generate a personalized media plan based on SimilarWeb analysis.

    Returns a dict with recommended channels, budget tiers, and talking points
    that can be injected into email templates.
    """
    visits = analysis.get("monthly_visits", 0)
    paid_pct = analysis.get("paid_search_pct", 0)
    bounce = analysis.get("bounce_rate", 50)
    mobile_pct = analysis.get("mobile_pct", 50)

    # Determine company tier by traffic
    if visits >= 100_000:
        tier = "enterprise"
        base_budget = 15_000
        phase_count = 3
    elif visits >= 10_000:
        tier = "growth"
        base_budget = 8_000
        phase_count = 2
    elif visits >= 1_000:
        tier = "starter"
        base_budget = 5_000
        phase_count = 2
    else:
        tier = "launch"
        base_budget = 3_000
        phase_count = 2

    # Adjust budget based on paid search gap
    if paid_pct < 1:
        opportunity = "massive"
        budget_multiplier = 1.2
    elif paid_pct < 5:
        opportunity = "significant"
        budget_multiplier = 1.0
    elif paid_pct < 15:
        opportunity = "optimization"
        budget_multiplier = 0.9
    else:
        opportunity = "efficiency"
        budget_multiplier = 0.8

    total_budget = int(base_budget * budget_multiplier * phase_count)

    # Recommend channels based on device split and traffic sources
    channels = ["Google Search"]
    if mobile_pct > 60:
        channels.append("Meta (FB/IG)")
    if analysis.get("social_pct", 0) > 5:
        channels.append("Reddit")
    channels.append("LinkedIn Ads")
    channels.append("Retargeting")

    # Projected traffic uplift
    if paid_pct < 1:
        uplift_low, uplift_high = 100, 200
    elif paid_pct < 5:
        uplift_low, uplift_high = 50, 100
    else:
        uplift_low, uplift_high = 20, 50

    projected_visits_low = int(visits * (1 + uplift_low / 100))
    projected_visits_high = int(visits * (1 + uplift_high / 100))

    # Build talking points
    talking_points = []
    if paid_pct < 1:
        talking_points.append(
            f"{company_name} gets {visits:,} monthly visits but only {paid_pct:.1f}% "
            f"from paid channels — competitors are likely capturing demand you're missing."
        )
    if bounce > 40:
        talking_points.append(
            f"With a {bounce:.0f}% bounce rate, retargeting could re-engage "
            f"thousands of visitors who left without converting."
        )
    if mobile_pct > 65:
        talking_points.append(
            f"{mobile_pct:.0f}% of your traffic is mobile — campaigns should be mobile-optimized."
        )

    return {
        "tier": tier,
        "opportunity_level": opportunity,
        "total_budget": total_budget,
        "phase_count": phase_count,
        "channels": channels,
        "projected_visits_low": projected_visits_low,
        "projected_visits_high": projected_visits_high,
        "uplift_low_pct": uplift_low,
        "uplift_high_pct": uplift_high,
        "talking_points": talking_points,
        "paid_search_pct": paid_pct,
        "monthly_visits": visits,
        "bounce_rate": bounce,
        "mobile_pct": mobile_pct,
    }
