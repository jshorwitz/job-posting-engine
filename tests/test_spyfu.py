"""Tests for engine/clients/spyfu.py."""

from __future__ import annotations

from base64 import b64encode
from unittest.mock import MagicMock, patch

import pytest

from engine.clients.spyfu import SpyFuClient, _normalize_domain
from engine.config import Settings


# ── Domain normalization ─────────────────────────────────────────


class TestNormalizeDomain:
    def test_strips_protocol(self):
        assert _normalize_domain("https://example.com") == "example.com"
        assert _normalize_domain("http://example.com") == "example.com"

    def test_strips_www(self):
        assert _normalize_domain("www.example.com") == "example.com"

    def test_strips_trailing_slash(self):
        assert _normalize_domain("example.com/") == "example.com"

    def test_lowercases(self):
        assert _normalize_domain("Example.COM") == "example.com"

    def test_full_url(self):
        assert _normalize_domain("https://www.Example.COM/page") == "example.com/page"

    def test_plain_domain(self):
        assert _normalize_domain("acme.io") == "acme.io"


# ── Client initialization ────────────────────────────────────────


class TestSpyFuClientInit:
    def test_raises_without_credentials(self):
        settings = Settings(spyfu_api_id="", spyfu_secret_key="")
        with pytest.raises(ValueError, match="SPYFU_API_ID"):
            SpyFuClient(settings)

    def test_builds_auth_header(self):
        settings = Settings(spyfu_api_id="myid", spyfu_secret_key="mysecret")
        client = SpyFuClient(settings)
        expected = f"Basic {b64encode(b'myid:mysecret').decode()}"
        assert client._auth_header == expected


# ── Domain stats parsing ─────────────────────────────────────────


class TestGetDomainStats:
    def _make_client(self) -> SpyFuClient:
        settings = Settings(spyfu_api_id="id", spyfu_secret_key="key")
        return SpyFuClient(settings)

    @patch.object(SpyFuClient, "_request")
    def test_parses_stats(self, mock_req: MagicMock):
        mock_req.return_value = {
            "ppcBudget": 5000,
            "monthlyOrganicClicks": 12000,
            "monthlyPaidClicks": 3000,
            "ppcKeywords": 150,
            "organicKeywords": 800,
            "adSpendMonthly": 5000,
            "domainStrength": 42,
        }
        client = self._make_client()
        result = client.get_domain_stats("example.com")

        assert result is not None
        assert result["ad_spend_monthly"] == 5000
        assert result["ad_spend_annual"] == 60000
        assert result["ppc_keyword_count"] == 150
        assert result["domain_strength"] == 42

    @patch.object(SpyFuClient, "_request")
    def test_returns_none_on_failure(self, mock_req: MagicMock):
        mock_req.return_value = None
        client = self._make_client()
        assert client.get_domain_stats("nope.com") is None


# ── Ad history parsing ───────────────────────────────────────────


class TestGetAdHistory:
    @patch.object(SpyFuClient, "_request")
    def test_parses_ads(self, mock_req: MagicMock):
        mock_req.return_value = {
            "totalResults": 2,
            "results": [
                {"title": "Best Product", "daysActive": 120, "description": "Buy now"},
                {"headline": "Second Ad", "totalDaysActive": 30, "body": "Try free"},
            ],
        }
        settings = Settings(spyfu_api_id="id", spyfu_secret_key="key")
        client = SpyFuClient(settings)
        result = client.get_ad_history("example.com", limit=10)

        assert result is not None
        assert result["total_ads"] == 2
        assert len(result["ads"]) == 2
        assert result["ads"][0]["headline"] == "Best Product"
        assert result["ads"][0]["days_active"] == 120
        assert result["ads"][1]["headline"] == "Second Ad"


# ── PPC keywords parsing ────────────────────────────────────────


class TestGetPpcKeywords:
    @patch.object(SpyFuClient, "_request")
    def test_parses_keywords(self, mock_req: MagicMock):
        mock_req.return_value = {
            "totalResults": 1,
            "results": [
                {"keyword": "saas tool", "cpc": 4.5, "position": 3, "searchVolume": 1200},
            ],
        }
        settings = Settings(spyfu_api_id="id", spyfu_secret_key="key")
        client = SpyFuClient(settings)
        result = client.get_ppc_keywords("example.com", limit=10)

        assert result is not None
        assert result["total_keywords"] == 1
        assert result["keywords"][0]["keyword"] == "saas tool"
        assert result["keywords"][0]["cpc"] == 4.5


# ── Competitors parsing ─────────────────────────────────────────


class TestGetCompetitors:
    @patch.object(SpyFuClient, "_request")
    def test_parses_ppc_competitors(self, mock_req: MagicMock):
        mock_req.side_effect = [
            {  # PPC
                "results": [
                    {"domain": "rival.com", "commonKeywords": 50, "estimatedBudget": 8000},
                ]
            },
            {  # Organic
                "results": []
            },
        ]
        settings = Settings(spyfu_api_id="id", spyfu_secret_key="key")
        client = SpyFuClient(settings)
        result = client.get_competitors("example.com")

        assert result is not None
        assert len(result["ppc_competitors"]) == 1
        assert result["ppc_competitors"][0]["domain"] == "rival.com"
        assert result["ppc_competitors"][0]["common_keywords"] == 50
