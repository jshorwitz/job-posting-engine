"""Multi-source enrichment orchestrator.

Coordinates SpyFu, BuiltWith, Firecrawl, and OpenAI to build a complete
enrichment profile for each lead. Called by pipeline.py's run_enrichment().

Data collection order (per docs/18-email-sequence.md):
  1. SpyFu getDomainStats    → spend, keywords, clicks
  2. SpyFu getCompetitors    → top competitor, shared keywords
  3. SpyFu getKombatAnalysis  → gap keyword + CPC
  4. SpyFu getAdHistory       → top headline, total ads
  5. SpyFu getSEOMetrics      → organic click value, top10
  6. SpyFu getPPCKeywords     → waste keywords (computed)
  7. BuiltWith                → ad pixels, CRM, analytics, tech stack
  8. Firecrawl                → homepage headline
  9. OpenAI                   → personalized opening line

Rate limiting:
  - SpyFu: ~100 req/hr → 7 calls per lead → max 14 leads/hr
  - BuiltWith: standard rate limits
  - Firecrawl: standard rate limits
  - OpenAI: generous limits
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import OpenAI

from engine.config import Settings

logger = logging.getLogger(__name__)

SPYFU_DELAY = 0.4  # seconds between SpyFu requests
SOURCE_DELAY = 0.2  # seconds between different source calls


def enrich_lead(
    settings: Settings,
    domain: str,
    company_name: str,
    contact_name: str,
    job_title_hiring: str,
    *,
    skip_spyfu: bool = False,
    skip_builtwith: bool = False,
    skip_firecrawl: bool = False,
    skip_synter: bool = False,
    skip_ai: bool = False,
) -> dict[str, Any]:
    """Enrich a single lead with all available data sources.

    Returns a flat dict with prefixed keys (spyfu_*, builtwith_*, etc.)
    ready for export to Instantly CSV or Loops contact properties.
    """
    result: dict[str, Any] = {
        "company_name": company_name,
        "company_domain": domain,
        "contact_name": contact_name,
        "job_title_hiring": job_title_hiring,
    }

    # ── SpyFu enrichment ─────────────────────────────────────────
    if not skip_spyfu and settings.spyfu_api_id and domain:
        result.update(_enrich_spyfu(settings, domain))

    # ── BuiltWith enrichment ─────────────────────────────────────
    if not skip_builtwith and settings.builtwith_api_key and domain:
        time.sleep(SOURCE_DELAY)
        result.update(_enrich_builtwith(settings, domain))

    # ── Firecrawl enrichment ─────────────────────────────────────
    if not skip_firecrawl and settings.firecrawl_api_key and domain:
        time.sleep(SOURCE_DELAY)
        result.update(_enrich_firecrawl(settings, domain))

    # ── Synter / SimilarWeb enrichment ─────────────────────────────
    if not skip_synter and settings.synter_api_key and settings.synter_enrich_enabled and domain:
        time.sleep(SOURCE_DELAY)
        result.update(_enrich_synter(settings, domain, company_name))

    # ── AI personalization ───────────────────────────────────────
    if not skip_ai and settings.openai_api_key:
        time.sleep(SOURCE_DELAY)
        result["ai_personalization"] = _generate_personalization(
            settings=settings,
            contact_name=contact_name,
            company_name=company_name,
            job_title_hiring=job_title_hiring,
            domain=domain,
            headline=result.get("firecrawl_headline", ""),
        )

    # ── Settings-derived fields ──────────────────────────────────
    result["settings_calendly_url"] = settings.calendly_url or ""

    return result


def _enrich_spyfu(settings: Settings, domain: str) -> dict[str, Any]:
    """Fetch all SpyFu data for a domain. Returns prefixed dict."""
    from engine.clients.spyfu import SpyFuClient

    data: dict[str, Any] = {}

    try:
        spyfu = SpyFuClient(settings)
    except ValueError:
        logger.warning("[Enrich] SpyFu credentials not configured")
        return data

    # 1. Domain stats
    stats = spyfu.get_domain_stats(domain)
    if stats:
        monthly = stats.get("ad_spend_monthly", 0)
        data["spyfu_monthly_spend"] = monthly
        data["spyfu_annual_spend"] = stats.get("ad_spend_annual", 0)
        data["spyfu_ppc_keywords"] = stats.get("ppc_keyword_count", 0)
        data["spyfu_organic_keywords"] = stats.get("organic_keyword_count", 0)
        data["spyfu_paid_clicks"] = stats.get("monthly_paid_clicks", 0)
        data["spyfu_organic_clicks"] = stats.get("monthly_organic_clicks", 0)
        data["spyfu_domain_strength"] = stats.get("domain_strength", 0)
    else:
        logger.info(f"[Enrich] SpyFu: no domain stats for {domain}")
        return data

    time.sleep(SPYFU_DELAY)

    # 2. Competitors
    competitors = spyfu.get_competitors(domain)
    if competitors and competitors.get("ppc_competitors"):
        top = competitors["ppc_competitors"][0]
        data["spyfu_top_competitor"] = top.get("domain", "")
        data["spyfu_competitor_spend"] = top.get("estimated_budget", 0)
        data["spyfu_shared_keywords"] = top.get("common_keywords", 0)

    time.sleep(SPYFU_DELAY)

    # 3. Kombat gap analysis (domain vs top competitor)
    top_comp = data.get("spyfu_top_competitor", "")
    if top_comp:
        kombat = spyfu.get_kombat([domain, top_comp])
        if kombat and kombat.get("gap_opportunities"):
            gap = kombat["gap_opportunities"][0]
            data["spyfu_gap_keyword"] = gap.get("keyword", "")
            data["spyfu_gap_keyword_cpc"] = gap.get("cpc", 0)

        time.sleep(SPYFU_DELAY)

    # 4. Ad history
    ad_history = spyfu.get_ad_history(domain, limit=10)
    if ad_history:
        data["spyfu_total_ads"] = ad_history.get("total_ads", 0)
        ads = ad_history.get("ads", [])
        if ads:
            best = max(ads, key=lambda a: a.get("days_active", 0))
            data["spyfu_top_headline"] = best.get("headline", "")
            data["spyfu_top_ad_days"] = best.get("days_active", 0)

    time.sleep(SPYFU_DELAY)

    # 5. SEO metrics
    seo = spyfu.get_seo_metrics(domain)
    if seo:
        data["spyfu_organic_click_value"] = seo.get("organic_click_value", 0)
        dist = seo.get("ranking_distribution", {})
        data["spyfu_seo_top10"] = (
            dist.get("positions_1_to_3", 0) + dist.get("positions_4_to_10", 0)
        )

    time.sleep(SPYFU_DELAY)

    # 6. PPC keywords (waste analysis)
    ppc = spyfu.get_ppc_keywords(domain, limit=50)
    if ppc:
        waste = 0
        for kw in ppc.get("keywords", []):
            if kw.get("cpc", 0) > 3 and kw.get("position", 0) > 8:
                waste += 1
        data["spyfu_waste_keywords"] = waste

    data["spyfu_top_ad_network"] = "Google Ads"  # SpyFu primarily tracks Google
    return data


def _enrich_builtwith(settings: Settings, domain: str) -> dict[str, Any]:
    """Fetch BuiltWith data for a domain. Returns prefixed dict."""
    from engine.clients.builtwith import BuiltWithClient

    data: dict[str, Any] = {}

    try:
        bw = BuiltWithClient(settings)
    except ValueError:
        logger.warning("[Enrich] BuiltWith credentials not configured")
        return data

    profile = bw.get_tech_profile(domain)
    if profile:
        data["builtwith_installed_pixels"] = profile.get("ad_platforms", [])
        data["builtwith_missing_pixels"] = profile.get("missing_platforms", [])
        data["builtwith_tech_stack"] = profile.get("tech_stack", "")
        data["builtwith_crm_tool"] = profile.get("crm_tool", "")
        data["builtwith_analytics_tool"] = profile.get("analytics_tool", "")
        data["builtwith_pixel_count"] = profile.get("pixel_count", 0)
    else:
        logger.info(f"[Enrich] BuiltWith: no data for {domain}")

    return data


def _enrich_firecrawl(settings: Settings, domain: str) -> dict[str, Any]:
    """Fetch Firecrawl data for a domain. Returns prefixed dict."""
    from engine.clients.firecrawl import FirecrawlClient

    data: dict[str, Any] = {}

    try:
        fc = FirecrawlClient(settings)
    except ValueError:
        logger.warning("[Enrich] Firecrawl credentials not configured")
        return data

    result = fc.get_headline(domain)
    if result:
        data["firecrawl_headline"] = result.get("headline", "")
        data["firecrawl_description"] = result.get("description", "")
    else:
        logger.info(f"[Enrich] Firecrawl: no headline for {domain}")

    return data


def _generate_personalization(
    settings: Settings,
    contact_name: str,
    company_name: str,
    job_title_hiring: str,
    domain: str,
    headline: str,
) -> str:
    """Generate a personalized opening line via OpenAI.

    Returns a single sentence (max 150 chars) that references something
    specific about the company, used as the Personalization column in Instantly.
    """
    first_name = contact_name.split()[0] if contact_name else "there"
    headline_ctx = f'Their homepage says: "{headline}".' if headline else ""

    prompt = f"""\
Write a single opening line (max 120 chars) for a cold email to {first_name}
at {company_name} ({domain}). They are hiring a {job_title_hiring}.
{headline_ctx}

Rules:
- Reference something specific about the company or their hiring signal
- NO generic phrases like "I noticed" or "I came across"
- NO emojis. Casual, peer-to-peer tone.
- Just the one line, nothing else.
"""

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=60,
        )
        line = (response.choices[0].message.content or "").strip().strip('"')
        return line[:150]
    except Exception as exc:
        logger.warning(f"[Enrich] AI personalization failed: {exc}")
        return ""


def _enrich_synter(settings: Settings, domain: str, company_name: str) -> dict[str, Any]:
    """Fetch SimilarWeb traffic data via Synter MCP and generate media plan.

    Returns prefixed dict with synter_* and mediaplan_* keys.
    """
    from engine.clients.synter import SynterClient, generate_media_plan

    data: dict[str, Any] = {}

    try:
        client = SynterClient(settings)
    except ValueError:
        logger.warning("[Enrich] Synter credentials not configured")
        return data

    analysis = client.analyze_domain(domain)
    if not analysis:
        logger.info(f"[Enrich] Synter: no data for {domain}")
        return data

    # Store raw SimilarWeb metrics
    data["synter_monthly_visits"] = analysis.get("monthly_visits", 0)
    data["synter_bounce_rate"] = analysis.get("bounce_rate", 0)
    data["synter_pages_per_visit"] = analysis.get("pages_per_visit", 0)
    data["synter_avg_duration"] = analysis.get("avg_visit_duration_sec", 0)
    data["synter_desktop_pct"] = analysis.get("desktop_pct", 0)
    data["synter_mobile_pct"] = analysis.get("mobile_pct", 0)
    data["synter_paid_search_pct"] = analysis.get("paid_search_pct", 0)
    data["synter_organic_pct"] = analysis.get("organic_search_pct", 0)
    data["synter_direct_pct"] = analysis.get("direct_pct", 0)
    data["synter_social_pct"] = analysis.get("social_pct", 0)
    data["synter_global_rank"] = analysis.get("global_rank", 0)

    # Generate personalized media plan
    plan = generate_media_plan(analysis, company_name)
    data["mediaplan_tier"] = plan["tier"]
    data["mediaplan_opportunity"] = plan["opportunity_level"]
    data["mediaplan_total_budget"] = plan["total_budget"]
    data["mediaplan_channels"] = ", ".join(plan["channels"])
    data["mediaplan_projected_visits_low"] = plan["projected_visits_low"]
    data["mediaplan_projected_visits_high"] = plan["projected_visits_high"]
    data["mediaplan_uplift_pct"] = f"{plan['uplift_low_pct']}-{plan['uplift_high_pct']}%"
    data["mediaplan_talking_points"] = " | ".join(plan["talking_points"])

    logger.info(
        f"[Enrich] Synter: {domain} → {analysis.get('monthly_visits', 0):,} visits, "
        f"{analysis.get('paid_search_pct', 0):.1f}% paid → {plan['tier']} tier, "
        f"${plan['total_budget']:,} plan"
    )

    return data
