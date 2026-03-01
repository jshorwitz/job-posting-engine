"""Export enriched leads to Instantly.ai CSV format.

Generates a CSV with all 37 columns defined in docs/18-email-sequence.md.
Each column becomes a custom variable in Instantly ({{ColumnName}}).

CSV rules (Instantly format):
  - Column names: CamelCase, max 20 chars, no duplicates
  - Email column must be first
  - UTF-8 encoding
  - Empty cells → Instantly uses {{Variable|fallback}} syntax
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Column order matches docs/18-email-sequence.md
CSV_COLUMNS = [
    "Email",
    "First Name",
    "Last Name",
    "Company Name",
    "Title",
    "Phone",
    "Personalization",
    "Jobtitle",
    "Companydomain",
    "Monthlyspend",
    "Annualspend",
    "Ppckeywords",
    "Organickeywords",
    "Paidclicks",
    "Organicclicks",
    "Domainstrength",
    "Topcompetitor",
    "Competitorspend",
    "Sharedkeywords",
    "Gapkeyword",
    "Gapkeywordcpc",
    "Topheadline",
    "Topaddays",
    "Totalads",
    "Installedpixels",
    "Missingpixels",
    "Pixelcount",
    "Orgclickvalue",
    "Seotop10",
    "Topadnetwork",
    "Wastekeywords",
    "Estimatedsavings",
    "Techstack",
    "Crmtool",
    "Analyticstool",
    "Siteheadline",
    "Callink",
]


def _fmt_money(amount: float | int | None) -> str:
    if not amount:
        return ""
    return f"${amount:,.0f}"


def _fmt_int(value: int | float | None) -> str:
    if not value:
        return ""
    return f"{int(value):,}"


def build_row(lead: dict[str, Any]) -> dict[str, str]:
    """Convert an enriched lead dict into an Instantly CSV row.

    The lead dict should contain keys from the enrichment pipeline:
        contact_*    — from Sumble/Hunter
        spyfu_*      — from SpyFu enrichment
        builtwith_*  — from BuiltWith
        firecrawl_*  — from Firecrawl
        ai_*         — from OpenAI personalization
        settings_*   — from engine config
    """
    # Contact info
    full_name = lead.get("contact_name", "")
    parts = full_name.split() if full_name else []
    first_name = parts[0] if parts else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    # SpyFu data
    monthly_spend = lead.get("spyfu_monthly_spend", 0) or 0
    annual_spend = lead.get("spyfu_annual_spend", 0) or monthly_spend * 12
    estimated_savings = monthly_spend * 0.20 if monthly_spend else 0

    # Competitor data
    top_competitor = lead.get("spyfu_top_competitor", "")
    competitor_spend = lead.get("spyfu_competitor_spend", 0)
    shared_keywords = lead.get("spyfu_shared_keywords", 0)

    # BuiltWith data
    installed_pixels = lead.get("builtwith_installed_pixels", [])
    missing_pixels = lead.get("builtwith_missing_pixels", [])

    return {
        "Email": lead.get("contact_email", ""),
        "First Name": first_name,
        "Last Name": last_name,
        "Company Name": lead.get("company_name", ""),
        "Title": lead.get("contact_title", ""),
        "Phone": lead.get("contact_phone", ""),
        "Personalization": lead.get("ai_personalization", ""),
        "Jobtitle": lead.get("job_title_hiring", ""),
        "Companydomain": lead.get("company_domain", ""),
        "Monthlyspend": _fmt_money(monthly_spend),
        "Annualspend": _fmt_money(annual_spend),
        "Ppckeywords": _fmt_int(lead.get("spyfu_ppc_keywords")),
        "Organickeywords": _fmt_int(lead.get("spyfu_organic_keywords")),
        "Paidclicks": _fmt_int(lead.get("spyfu_paid_clicks")),
        "Organicclicks": _fmt_int(lead.get("spyfu_organic_clicks")),
        "Domainstrength": _fmt_int(lead.get("spyfu_domain_strength")),
        "Topcompetitor": top_competitor,
        "Competitorspend": _fmt_money(competitor_spend),
        "Sharedkeywords": _fmt_int(shared_keywords),
        "Gapkeyword": lead.get("spyfu_gap_keyword", ""),
        "Gapkeywordcpc": _fmt_money(lead.get("spyfu_gap_keyword_cpc")),
        "Topheadline": lead.get("spyfu_top_headline", ""),
        "Topaddays": _fmt_int(lead.get("spyfu_top_ad_days")),
        "Totalads": _fmt_int(lead.get("spyfu_total_ads")),
        "Installedpixels": ", ".join(installed_pixels) if isinstance(installed_pixels, list) else str(installed_pixels),
        "Missingpixels": ", ".join(missing_pixels) if isinstance(missing_pixels, list) else str(missing_pixels),
        "Pixelcount": str(len(installed_pixels)) if isinstance(installed_pixels, list) else "",
        "Orgclickvalue": _fmt_money(lead.get("spyfu_organic_click_value")),
        "Seotop10": _fmt_int(lead.get("spyfu_seo_top10")),
        "Topadnetwork": lead.get("spyfu_top_ad_network", "Google Ads"),
        "Wastekeywords": _fmt_int(lead.get("spyfu_waste_keywords")),
        "Estimatedsavings": _fmt_money(estimated_savings),
        "Techstack": lead.get("builtwith_tech_stack", ""),
        "Crmtool": lead.get("builtwith_crm_tool", ""),
        "Analyticstool": lead.get("builtwith_analytics_tool", ""),
        "Siteheadline": lead.get("firecrawl_headline", ""),
        "Callink": lead.get("settings_calendly_url", ""),
    }


def export_csv(
    leads: list[dict[str, Any]],
    output_path: str | Path | None = None,
) -> Path:
    """Export enriched leads to Instantly CSV format.

    Args:
        leads:       List of enriched lead dicts.
        output_path: Optional output file path. Defaults to
                     data/instantly-upload-YYYY-MM-DD.csv.

    Returns:
        Path to the generated CSV file.
    """
    if output_path is None:
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        output_path = data_dir / f"instantly-upload-{today}.csv"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Filter out leads without email (Instantly requires it)
    valid_leads = [l for l in leads if l.get("contact_email")]
    skipped = len(leads) - len(valid_leads)
    if skipped:
        logger.warning(f"Skipped {skipped} leads without email")

    rows = [build_row(lead) for lead in valid_leads]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} leads to {path}")
    return path
