"""SpyFu API client for competitive PPC/SEO intelligence.

Ported from apps/web/src/lib/spyfu/client.ts. Provides domain stats,
ad history, PPC keywords, competitors, and Kombat (gap analysis).

API base: https://api.spyfu.com
Auth: HTTP Basic (SPYFU_API_ID:SPYFU_SECRET_KEY)
Rate limits: ~100 requests/hour — enforced by caller via QUEUE_DELAY_MS.
"""

from __future__ import annotations

import logging
import re
import time
from base64 import b64encode
from typing import Any

import httpx

from engine.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.spyfu.com"
TIMEOUT = 15.0
QUEUE_DELAY = 0.3  # seconds between requests


def _normalize_domain(domain: str) -> str:
    """Strip protocol, www., and trailing slash."""
    d = re.sub(r"^https?://", "", domain)
    d = re.sub(r"^www\.", "", d)
    return d.rstrip("/").lower()


class SpyFuClient:
    """Fetch competitive PPC/SEO intelligence from SpyFu."""

    def __init__(self, settings: Settings) -> None:
        if not settings.spyfu_api_id or not settings.spyfu_secret_key:
            raise ValueError("SPYFU_API_ID and SPYFU_SECRET_KEY are required")
        creds = f"{settings.spyfu_api_id}:{settings.spyfu_secret_key}"
        self._auth_header = f"Basic {b64encode(creds.encode()).decode()}"

    # ── Core request ──────────────────────────────────────────────

    def _request(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Make authenticated GET to SpyFu API. Returns JSON or None."""
        url = f"{BASE_URL}{endpoint}"
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.get(url, params=params or {}, headers=headers)

            if resp.status_code == 429:
                logger.warning("[SpyFu] Rate limited (429). Backing off 10s.")
                time.sleep(10)
                return None

            if resp.status_code != 200:
                logger.warning(
                    f"[SpyFu] {endpoint} returned {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
                return None

            return resp.json()

        except httpx.TimeoutException:
            logger.error(f"[SpyFu] Timeout on {endpoint}")
            return None
        except Exception as exc:
            logger.error(f"[SpyFu] Request error on {endpoint}: {exc}")
            return None

    # ── Domain Stats ──────────────────────────────────────────────

    def get_domain_stats(self, domain: str) -> dict[str, Any] | None:
        """Get comprehensive domain statistics (PPC budget, keywords, etc.).

        Maps to: /apis/domain_stats_api/v2/getLatestDomainStats
        """
        d = _normalize_domain(domain)
        data = self._request(
            "/apis/domain_stats_api/v2/getLatestDomainStats",
            {"domain": d},
        )
        if not data:
            return None

        monthly_budget = data.get("ppcBudget") or data.get("monthlyPpcBudget") or 0
        return {
            "domain": d,
            "monthly_ppc_budget": monthly_budget,
            "monthly_organic_clicks": data.get("monthlyOrganicClicks", 0),
            "monthly_paid_clicks": data.get("monthlyPaidClicks", 0),
            "ppc_keyword_count": data.get("ppcKeywords") or data.get("ppcKeywordCount") or 0,
            "organic_keyword_count": data.get("organicKeywords") or data.get("organicKeywordCount") or 0,
            "ad_spend_monthly": data.get("adSpendMonthly") or monthly_budget,
            "ad_spend_annual": (data.get("adSpendMonthly") or monthly_budget) * 12,
            "domain_strength": data.get("domainStrength") or data.get("strength") or 0,
            "backlinks": data.get("backlinks", 0),
            "referring_domains": data.get("referringDomains", 0),
            "first_seen": data.get("firstSeen") or data.get("firstSeenDate") or "",
        }

    # ── Ad History ────────────────────────────────────────────────

    def get_ad_history(self, domain: str, limit: int = 50) -> dict[str, Any] | None:
        """Get historical ad copy for a domain.

        Maps to: /apis/ad_history_api/v2/getDomainAds
        """
        d = _normalize_domain(domain)
        data = self._request(
            "/apis/ad_history_api/v2/getDomainAds",
            {"domain": d, "pageSize": str(limit)},
        )
        if not data:
            return None

        ads = []
        for ad in data.get("results") or data.get("ads") or []:
            ads.append({
                "headline": ad.get("title") or ad.get("headline") or "",
                "description": ad.get("description") or ad.get("body") or "",
                "display_url": ad.get("displayUrl", ""),
                "destination_url": ad.get("destinationUrl") or ad.get("landingPage") or "",
                "keyword": ad.get("keyword", ""),
                "first_seen": ad.get("firstSeen") or ad.get("firstSeenDate") or "",
                "last_seen": ad.get("lastSeen") or ad.get("lastSeenDate") or "",
                "days_active": ad.get("daysActive") or ad.get("totalDaysActive") or 0,
                "position": ad.get("avgPosition") or ad.get("position") or 0,
            })

        return {
            "domain": d,
            "total_ads": data.get("totalResults") or len(ads),
            "ads": ads,
        }

    # ── PPC Keywords ──────────────────────────────────────────────

    def get_ppc_keywords(self, domain: str, limit: int = 100) -> dict[str, Any] | None:
        """Get PPC keywords for a domain.

        Maps to: /apis/ppc_api/v2/getDomainPpcKeywords
        """
        d = _normalize_domain(domain)
        data = self._request(
            "/apis/ppc_api/v2/getDomainPpcKeywords",
            {"domain": d, "pageSize": str(limit)},
        )
        if not data:
            return None

        keywords = []
        for kw in data.get("results") or data.get("keywords") or []:
            keywords.append({
                "keyword": kw.get("keyword") or kw.get("term") or "",
                "search_volume": kw.get("searchVolume") or kw.get("exactLocalMonthlySearchVolume") or 0,
                "cpc": kw.get("cpc") or kw.get("costPerClick") or 0,
                "position": kw.get("rankPosition") or kw.get("position") or 0,
                "clicks": kw.get("clicks") or kw.get("monthlyClicks") or 0,
                "cost": kw.get("cost") or kw.get("monthlyCost") or 0,
                "difficulty": kw.get("difficulty") or kw.get("keywordDifficulty") or 0,
            })

        return {
            "domain": d,
            "total_keywords": data.get("totalResults") or len(keywords),
            "estimated_monthly_budget": data.get("estimatedMonthlyBudget") or data.get("totalMonthlyCost") or 0,
            "estimated_monthly_clicks": data.get("estimatedMonthlyClicks") or data.get("totalMonthlyClicks") or 0,
            "keywords": keywords,
        }

    # ── Competitors ───────────────────────────────────────────────

    def get_competitors(self, domain: str) -> dict[str, Any] | None:
        """Get top PPC and organic competitors.

        Maps to: /apis/competitors_api/v2/ppc|organic/getTopCompetitors
        """
        d = _normalize_domain(domain)

        def _map_competitor(c: dict) -> dict:
            return {
                "domain": c.get("domain") or c.get("competitorDomain") or "",
                "common_keywords": c.get("commonKeywords") or c.get("sharedKeywords") or 0,
                "competition_strength": c.get("competitionStrength") or c.get("strength") or 0,
                "estimated_budget": c.get("estimatedBudget") or c.get("monthlyBudget") or 0,
                "overlap_percentage": c.get("overlapPercentage") or c.get("overlap") or 0,
            }

        ppc_competitors: list[dict] = []
        organic_competitors: list[dict] = []

        # PPC competitors
        ppc_data = self._request(
            "/apis/competitors_api/v2/ppc/getTopCompetitors",
            {"domain": d},
        )
        if ppc_data:
            raw = ppc_data.get("results") or ppc_data.get("competitors") or []
            ppc_competitors = [_map_competitor(c) for c in raw]

        time.sleep(QUEUE_DELAY)

        # Organic competitors
        org_data = self._request(
            "/apis/competitors_api/v2/organic/getTopCompetitors",
            {"domain": d},
        )
        if org_data:
            raw = org_data.get("results") or org_data.get("competitors") or []
            organic_competitors = [_map_competitor(c) for c in raw]

        return {
            "domain": d,
            "ppc_competitors": ppc_competitors,
            "organic_competitors": organic_competitors,
        }

    # ── SEO Metrics ───────────────────────────────────────────────

    def get_seo_metrics(self, domain: str) -> dict[str, Any] | None:
        """Get SEO metrics for a domain.

        Maps to: /apis/seo_api/v2/getDomainSeoStats
        """
        d = _normalize_domain(domain)
        data = self._request(
            "/apis/seo_api/v2/getDomainSeoStats",
            {"domain": d},
        )
        if not data:
            return None

        top_pages = []
        for p in data.get("topPages") or data.get("pages") or []:
            top_pages.append({
                "url": p.get("url") or p.get("page") or "",
                "keywords": p.get("keywords") or p.get("keywordCount") or 0,
                "monthly_clicks": p.get("monthlyClicks") or p.get("clicks") or 0,
                "click_value": p.get("clickValue") or p.get("value") or 0,
            })

        return {
            "domain": d,
            "organic_keywords": data.get("organicKeywords") or data.get("totalKeywords") or 0,
            "monthly_organic_clicks": data.get("monthlyOrganicClicks") or data.get("monthlyClicks") or 0,
            "organic_click_value": data.get("organicClickValue") or data.get("clickValue") or 0,
            "top_pages": top_pages,
            "ranking_distribution": {
                "positions_1_to_3": data.get("positions1to3") or data.get("top3") or 0,
                "positions_4_to_10": data.get("positions4to10") or data.get("top10") or 0,
                "positions_11_to_20": data.get("positions11to20") or data.get("top20") or 0,
                "positions_21_to_50": data.get("positions21to50") or data.get("top50") or 0,
            },
        }

    # ── Kombat (Gap Analysis) ─────────────────────────────────────

    def get_kombat(self, domains: list[str]) -> dict[str, Any] | None:
        """Keyword gap/overlap analysis between 2+ domains.

        Maps to: /apis/kombat_api/v2/getKombatData
        """
        if len(domains) < 2:
            logger.error("[SpyFu] Kombat requires at least 2 domains")
            return None

        normalized = [_normalize_domain(d) for d in domains]
        data = self._request(
            "/apis/kombat_api/v2/getKombatData",
            {"domains": ",".join(normalized)},
        )
        if not data:
            return None

        def _map_kw(kw: dict) -> dict:
            return {
                "keyword": kw.get("keyword") or kw.get("term") or "",
                "search_volume": kw.get("searchVolume", 0),
                "cpc": kw.get("cpc", 0),
                "difficulty": kw.get("difficulty", 0),
                "domains": kw.get("domains") or kw.get("rankingDomains") or [],
            }

        # Build unique keywords with robust key matching
        raw_unique = data.get("uniqueKeywords", {})
        unique_by_domain: dict[str, list[dict]] = {}
        for d in normalized:
            candidates = [d, f"www.{d}", re.sub(r"^www\.", "", d)]
            raw_kws = next(
                (raw_unique[c] for c in candidates if isinstance(raw_unique.get(c), list)),
                [],
            )
            unique_by_domain[d] = [_map_kw(kw) for kw in raw_kws]

        return {
            "domains": normalized,
            "shared_keywords": [_map_kw(kw) for kw in data.get("sharedKeywords") or data.get("overlap") or []],
            "unique_keywords": unique_by_domain,
            "gap_opportunities": [_map_kw(kw) for kw in data.get("gapOpportunities") or data.get("gaps") or []],
            "overlap_count": data.get("overlapCount", 0),
            "total_analyzed_keywords": data.get("totalKeywords", 0),
        }

    # ── Convenience: full enrichment for follow-ups ───────────────

    def enrich_domain(self, domain: str) -> dict[str, Any] | None:
        """Fetch domain stats + competitors + ad history + SEO in one call.

        Returns a flat dict compatible with the old AdBeat interface
        (estimated_monthly_spend, etc.) plus richer SpyFu fields, or None.
        """
        stats = self.get_domain_stats(domain)
        if not stats:
            logger.info(f"[SpyFu] No domain stats for {domain}")
            return None

        monthly_spend = stats.get("ad_spend_monthly", 0)
        if monthly_spend < 1:
            logger.info(f"[SpyFu] {domain} has ~$0 ad spend — skipping enrichment")
            return None

        time.sleep(QUEUE_DELAY)

        # Fetch competitors (best-effort)
        competitors = self.get_competitors(domain)
        top_competitor = ""
        competitor_spend = 0
        if competitors and competitors.get("ppc_competitors"):
            top = competitors["ppc_competitors"][0]
            top_competitor = top.get("domain", "")
            competitor_spend = top.get("estimated_budget", 0)

        time.sleep(QUEUE_DELAY)

        # Ad history (best-effort, top 10)
        ad_history = self.get_ad_history(domain, limit=10)
        top_headline = ""
        top_ad_days = 0
        total_ads = 0
        if ad_history:
            total_ads = ad_history.get("total_ads", 0)
            if ad_history.get("ads"):
                best = max(ad_history["ads"], key=lambda a: a.get("days_active", 0))
                top_headline = best.get("headline", "")
                top_ad_days = best.get("days_active", 0)

        time.sleep(QUEUE_DELAY)

        # SEO metrics (best-effort)
        seo = self.get_seo_metrics(domain)
        organic_click_value = 0
        seo_top10 = 0
        if seo:
            organic_click_value = seo.get("organic_click_value", 0)
            dist = seo.get("ranking_distribution", {})
            seo_top10 = dist.get("positions_1_to_3", 0) + dist.get("positions_4_to_10", 0)

        time.sleep(QUEUE_DELAY)

        # PPC keywords (best-effort, top 20 for waste analysis)
        ppc = self.get_ppc_keywords(domain, limit=20)
        ppc_keywords = 0
        waste_keywords = 0
        estimated_savings = 0.0
        if ppc:
            ppc_keywords = ppc.get("total_keywords", 0)
            # "Waste" = low-quality-score proxied by high CPC + low position
            for kw in ppc.get("keywords", []):
                if kw.get("cpc", 0) > 5 and kw.get("position", 0) > 5:
                    waste_keywords += 1
                    estimated_savings += kw.get("cost", 0) * 0.2

        # Return AdBeat-compatible keys plus SpyFu extras
        return {
            # AdBeat-compatible (used by followup_writer / loops_sender)
            "estimated_monthly_spend": monthly_spend,
            "estimated_total_spend": stats.get("ad_spend_annual", 0),
            "months_analyzed": 12,
            # SpyFu-specific enrichment
            "domain": stats.get("domain", domain),
            "monthly_ppc_budget": monthly_spend,
            "annual_spend": stats.get("ad_spend_annual", 0),
            "ppc_keywords": ppc_keywords or stats.get("ppc_keyword_count", 0),
            "organic_keywords": stats.get("organic_keyword_count", 0),
            "paid_clicks": stats.get("monthly_paid_clicks", 0),
            "organic_clicks": stats.get("monthly_organic_clicks", 0),
            "domain_strength": stats.get("domain_strength", 0),
            "top_competitor": top_competitor,
            "competitor_spend": competitor_spend,
            "top_headline": top_headline,
            "top_ad_days": top_ad_days,
            "total_ads": total_ads,
            "organic_click_value": organic_click_value,
            "seo_top10": seo_top10,
            "waste_keywords": waste_keywords,
            "estimated_savings": estimated_savings,
        }
