"""Tests for engine/clients/builtwith.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.clients.builtwith import (
    ALL_AD_PLATFORMS,
    BuiltWithClient,
    _normalize_domain,
)
from engine.config import Settings


# ── Domain normalization ─────────────────────────────────────────


class TestNormalizeDomain:
    def test_strips_protocol_and_www(self):
        assert _normalize_domain("https://www.example.com/page") == "example.com"

    def test_lowercases(self):
        assert _normalize_domain("Example.COM") == "example.com"


# ── Client initialization ────────────────────────────────────────


class TestBuiltWithClientInit:
    def test_raises_without_key(self):
        settings = Settings(builtwith_api_key="")
        with pytest.raises(ValueError, match="BUILTWITH_API_KEY"):
            BuiltWithClient(settings)

    def test_stores_key(self):
        settings = Settings(builtwith_api_key="bw-test-key")
        client = BuiltWithClient(settings)
        assert client._api_key == "bw-test-key"


# ── Tech profile parsing ────────────────────────────────────────


class TestGetTechProfile:
    def _make_client(self) -> BuiltWithClient:
        settings = Settings(builtwith_api_key="test-key")
        return BuiltWithClient(settings)

    def _mock_response(self, technologies: list[dict]) -> dict:
        """Build a BuiltWith API response with given technologies."""
        return {
            "Results": [
                {
                    "Result": {
                        "Paths": [
                            {"Technologies": technologies}
                        ]
                    }
                }
            ]
        }

    @patch("engine.clients.builtwith.httpx.Client")
    def test_detects_google_pixel(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = self._mock_response([
            {"Name": "Google Ads Conversion Tracking"},
            {"Name": "Google Tag Manager"},
        ])
        mock_http.return_value.__enter__ = MagicMock(return_value=MagicMock(get=MagicMock(return_value=resp)))
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_tech_profile("example.com")

        assert result is not None
        assert "Google" in result["ad_platforms"]
        assert result["pixel_count"] >= 1

    @patch("engine.clients.builtwith.httpx.Client")
    def test_detects_meta_pixel(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = self._mock_response([
            {"Name": "Facebook Pixel"},
        ])
        mock_http.return_value.__enter__ = MagicMock(return_value=MagicMock(get=MagicMock(return_value=resp)))
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_tech_profile("example.com")

        assert result is not None
        assert "Meta" in result["ad_platforms"]

    @patch("engine.clients.builtwith.httpx.Client")
    def test_detects_crm(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = self._mock_response([
            {"Name": "HubSpot CRM"},
            {"Name": "Google Analytics 4"},
        ])
        mock_http.return_value.__enter__ = MagicMock(return_value=MagicMock(get=MagicMock(return_value=resp)))
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_tech_profile("example.com")

        assert result is not None
        assert result["crm_tool"] == "HubSpot CRM"
        assert result["analytics_tool"] == "Google Analytics 4"

    @patch("engine.clients.builtwith.httpx.Client")
    def test_missing_platforms(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = self._mock_response([
            {"Name": "Google Ads"},
        ])
        mock_http.return_value.__enter__ = MagicMock(return_value=MagicMock(get=MagicMock(return_value=resp)))
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_tech_profile("example.com")

        assert result is not None
        # All platforms except Google should be "missing"
        expected_missing = sorted(ALL_AD_PLATFORMS - {"Google"})
        assert result["missing_platforms"] == expected_missing

    @patch("engine.clients.builtwith.httpx.Client")
    def test_returns_none_on_404(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 404
        mock_http.return_value.__enter__ = MagicMock(return_value=MagicMock(get=MagicMock(return_value=resp)))
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        assert client.get_tech_profile("nope.com") is None

    @patch("engine.clients.builtwith.httpx.Client")
    def test_tech_stack_top5(self, mock_http: MagicMock):
        techs = [{"Name": f"Tech{i}"} for i in range(10)]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = self._mock_response(techs)
        mock_http.return_value.__enter__ = MagicMock(return_value=MagicMock(get=MagicMock(return_value=resp)))
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_tech_profile("example.com")

        assert result is not None
        stack_items = result["tech_stack"].split(", ")
        assert len(stack_items) == 5
