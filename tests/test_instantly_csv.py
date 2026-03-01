"""Tests for engine/export/instantly_csv.py."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from engine.export.instantly_csv import (
    CSV_COLUMNS,
    _fmt_int,
    _fmt_money,
    build_row,
    export_csv,
)


# ── Formatting helpers ───────────────────────────────────────────


class TestFmtMoney:
    def test_formats_dollars(self):
        assert _fmt_money(5000) == "$5,000"

    def test_formats_large_amount(self):
        assert _fmt_money(1234567) == "$1,234,567"

    def test_returns_empty_for_zero(self):
        assert _fmt_money(0) == ""

    def test_returns_empty_for_none(self):
        assert _fmt_money(None) == ""

    def test_formats_float(self):
        assert _fmt_money(42.7) == "$43"


class TestFmtInt:
    def test_formats_thousands(self):
        assert _fmt_int(1500) == "1,500"

    def test_returns_empty_for_zero(self):
        assert _fmt_int(0) == ""

    def test_returns_empty_for_none(self):
        assert _fmt_int(None) == ""


# ── Row building ─────────────────────────────────────────────────


class TestBuildRow:
    def _sample_lead(self) -> dict:
        return {
            "contact_email": "jane@acme.com",
            "contact_name": "Jane Doe",
            "contact_title": "Head of Growth",
            "company_name": "Acme Corp",
            "company_domain": "acme.com",
            "job_title_hiring": "Head of Growth",
            "spyfu_monthly_spend": 8000,
            "spyfu_annual_spend": 96000,
            "spyfu_ppc_keywords": 150,
            "spyfu_organic_keywords": 800,
            "spyfu_paid_clicks": 3000,
            "spyfu_organic_clicks": 12000,
            "spyfu_domain_strength": 42,
            "spyfu_top_competitor": "rival.com",
            "spyfu_competitor_spend": 12000,
            "spyfu_shared_keywords": 50,
            "spyfu_gap_keyword": "saas analytics",
            "spyfu_gap_keyword_cpc": 4.5,
            "spyfu_top_headline": "Best SaaS Tool",
            "spyfu_top_ad_days": 120,
            "spyfu_total_ads": 35,
            "spyfu_organic_click_value": 5200,
            "spyfu_seo_top10": 25,
            "spyfu_top_ad_network": "Google Ads",
            "spyfu_waste_keywords": 8,
            "builtwith_installed_pixels": ["Google", "Meta"],
            "builtwith_missing_pixels": ["LinkedIn", "Reddit"],
            "builtwith_tech_stack": "React, Next.js, Vercel",
            "builtwith_crm_tool": "HubSpot",
            "builtwith_analytics_tool": "GA4",
            "firecrawl_headline": "We Build Better Ads",
            "ai_personalization": "Congrats on the growth hire.",
            "settings_calendly_url": "https://cal.com/test/15",
        }

    def test_maps_email(self):
        row = build_row(self._sample_lead())
        assert row["Email"] == "jane@acme.com"

    def test_splits_name(self):
        row = build_row(self._sample_lead())
        assert row["First Name"] == "Jane"
        assert row["Last Name"] == "Doe"

    def test_formats_spend_as_money(self):
        row = build_row(self._sample_lead())
        assert row["Monthlyspend"] == "$8,000"
        assert row["Annualspend"] == "$96,000"

    def test_formats_keywords_as_int(self):
        row = build_row(self._sample_lead())
        assert row["Ppckeywords"] == "150"

    def test_joins_pixels(self):
        row = build_row(self._sample_lead())
        assert row["Installedpixels"] == "Google, Meta"
        assert row["Missingpixels"] == "LinkedIn, Reddit"

    def test_pixel_count(self):
        row = build_row(self._sample_lead())
        assert row["Pixelcount"] == "2"

    def test_personalization(self):
        row = build_row(self._sample_lead())
        assert row["Personalization"] == "Congrats on the growth hire."

    def test_calendly_link(self):
        row = build_row(self._sample_lead())
        assert row["Callink"] == "https://cal.com/test/15"

    def test_estimated_savings_computed(self):
        row = build_row(self._sample_lead())
        # 20% of $8,000 = $1,600
        assert row["Estimatedsavings"] == "$1,600"

    def test_handles_empty_lead(self):
        row = build_row({})
        assert row["Email"] == ""
        assert row["First Name"] == ""
        assert row["Monthlyspend"] == ""

    def test_all_columns_present(self):
        row = build_row(self._sample_lead())
        for col in CSV_COLUMNS:
            assert col in row, f"Missing column: {col}"


# ── CSV export ───────────────────────────────────────────────────


class TestExportCsv:
    def test_writes_csv_file(self, tmp_path: Path):
        leads = [
            {
                "contact_email": "a@test.com",
                "contact_name": "Alice A",
                "company_name": "Test Co",
                "company_domain": "test.com",
                "job_title_hiring": "Growth",
            },
        ]
        out = tmp_path / "test.csv"
        result = export_csv(leads, output_path=out)

        assert result == out
        assert out.exists()

        with open(out) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["Email"] == "a@test.com"
            assert rows[0]["First Name"] == "Alice"

    def test_skips_leads_without_email(self, tmp_path: Path):
        leads = [
            {"contact_name": "No Email"},
            {"contact_email": "b@test.com", "contact_name": "Has Email"},
        ]
        out = tmp_path / "test.csv"
        export_csv(leads, output_path=out)

        with open(out) as f:
            rows = list(csv.DictReader(f))
            assert len(rows) == 1

    def test_header_matches_columns(self, tmp_path: Path):
        out = tmp_path / "test.csv"
        export_csv([{"contact_email": "x@x.com"}], output_path=out)

        with open(out) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == CSV_COLUMNS

    def test_default_path_created(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        leads = [{"contact_email": "c@c.com"}]
        result = export_csv(leads)

        assert result.exists()
        assert "instantly-upload-" in result.name
        assert result.parent.name == "data"
