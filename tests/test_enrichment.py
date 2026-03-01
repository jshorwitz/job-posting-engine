"""Tests for engine/enrichment.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.config import Settings
from engine.enrichment import enrich_lead


def _base_settings(**overrides) -> Settings:
    defaults = {
        "spyfu_api_id": "id",
        "spyfu_secret_key": "key",
        "builtwith_api_key": "bw-key",
        "firecrawl_api_key": "fc-key",
        "openai_api_key": "sk-test",
        "calendly_url": "https://cal.com/test/15",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestEnrichLead:
    def test_returns_base_fields(self):
        """Even with all sources skipped, base fields are present."""
        settings = _base_settings()
        result = enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane Doe",
            job_title_hiring="Head of Growth",
            skip_spyfu=True,
            skip_builtwith=True,
            skip_firecrawl=True,
            skip_ai=True,
        )

        assert result["company_name"] == "Acme"
        assert result["company_domain"] == "acme.com"
        assert result["contact_name"] == "Jane Doe"
        assert result["job_title_hiring"] == "Head of Growth"
        assert result["settings_calendly_url"] == "https://cal.com/test/15"

    @patch("engine.enrichment._enrich_spyfu")
    def test_skip_spyfu_flag(self, mock_spyfu: MagicMock):
        settings = _base_settings()
        enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane",
            job_title_hiring="Growth",
            skip_spyfu=True,
            skip_builtwith=True,
            skip_firecrawl=True,
            skip_ai=True,
        )
        mock_spyfu.assert_not_called()

    @patch("engine.enrichment._enrich_spyfu")
    def test_calls_spyfu_when_enabled(self, mock_spyfu: MagicMock):
        mock_spyfu.return_value = {"spyfu_monthly_spend": 5000}
        settings = _base_settings()
        result = enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane",
            job_title_hiring="Growth",
            skip_spyfu=False,
            skip_builtwith=True,
            skip_firecrawl=True,
            skip_ai=True,
        )
        mock_spyfu.assert_called_once_with(settings, "acme.com")
        assert result["spyfu_monthly_spend"] == 5000

    @patch("engine.enrichment._enrich_builtwith")
    def test_skip_builtwith_flag(self, mock_bw: MagicMock):
        settings = _base_settings()
        enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane",
            job_title_hiring="Growth",
            skip_spyfu=True,
            skip_builtwith=True,
            skip_firecrawl=True,
            skip_ai=True,
        )
        mock_bw.assert_not_called()

    @patch("engine.enrichment._enrich_firecrawl")
    def test_skip_firecrawl_flag(self, mock_fc: MagicMock):
        settings = _base_settings()
        enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane",
            job_title_hiring="Growth",
            skip_spyfu=True,
            skip_builtwith=True,
            skip_firecrawl=True,
            skip_ai=True,
        )
        mock_fc.assert_not_called()

    @patch("engine.enrichment._generate_personalization")
    def test_skip_ai_flag(self, mock_ai: MagicMock):
        settings = _base_settings()
        enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane",
            job_title_hiring="Growth",
            skip_spyfu=True,
            skip_builtwith=True,
            skip_firecrawl=True,
            skip_ai=True,
        )
        mock_ai.assert_not_called()

    def test_skips_spyfu_without_credentials(self):
        """SpyFu is skipped when no API credentials are set."""
        settings = _base_settings(spyfu_api_id="", spyfu_secret_key="")
        result = enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane",
            job_title_hiring="Growth",
            skip_builtwith=True,
            skip_firecrawl=True,
            skip_ai=True,
        )
        # Should succeed without SpyFu data
        assert "spyfu_monthly_spend" not in result

    def test_skips_ai_without_openai_key(self):
        settings = _base_settings(openai_api_key="")
        result = enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme",
            contact_name="Jane",
            job_title_hiring="Growth",
            skip_spyfu=True,
            skip_builtwith=True,
            skip_firecrawl=True,
        )
        assert "ai_personalization" not in result

    @patch("engine.enrichment._enrich_spyfu")
    @patch("engine.enrichment._enrich_builtwith")
    @patch("engine.enrichment._enrich_firecrawl")
    @patch("engine.enrichment._generate_personalization")
    def test_full_enrichment(
        self,
        mock_ai: MagicMock,
        mock_fc: MagicMock,
        mock_bw: MagicMock,
        mock_spyfu: MagicMock,
    ):
        mock_spyfu.return_value = {"spyfu_monthly_spend": 10000}
        mock_bw.return_value = {"builtwith_pixel_count": 3}
        mock_fc.return_value = {"firecrawl_headline": "We Build Great Ads"}
        mock_ai.return_value = "Congrats on the growth hire."

        settings = _base_settings()
        result = enrich_lead(
            settings,
            domain="acme.com",
            company_name="Acme Corp",
            contact_name="Jane Doe",
            job_title_hiring="Head of Growth",
        )

        assert result["spyfu_monthly_spend"] == 10000
        assert result["builtwith_pixel_count"] == 3
        assert result["firecrawl_headline"] == "We Build Great Ads"
        assert result["ai_personalization"] == "Congrats on the growth hire."
