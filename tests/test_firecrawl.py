"""Tests for engine/clients/firecrawl.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.clients.firecrawl import FirecrawlClient
from engine.config import Settings


class TestFirecrawlClientInit:
    def test_raises_without_key(self):
        settings = Settings(firecrawl_api_key="")
        with pytest.raises(ValueError, match="FIRECRAWL_API_KEY"):
            FirecrawlClient(settings)


class TestGetHeadline:
    def _make_client(self) -> FirecrawlClient:
        settings = Settings(firecrawl_api_key="fc-test-key")
        return FirecrawlClient(settings)

    @patch("engine.clients.firecrawl.httpx.Client")
    def test_extracts_h1_from_markdown(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "success": True,
            "data": {
                "markdown": "# We Build Better Ads\n\nSome content below the heading.",
                "metadata": {
                    "title": "Acme Corp",
                    "description": "Acme helps you grow.",
                },
            },
        }
        mock_http.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=resp))
        )
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_headline("acme.com")

        assert result is not None
        assert result["headline"] == "We Build Better Ads"
        assert result["description"] == "Acme helps you grow."
        assert result["title"] == "Acme Corp"

    @patch("engine.clients.firecrawl.httpx.Client")
    def test_fallback_to_og_title(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "success": True,
            "data": {
                "markdown": "No heading here, just paragraphs.",
                "metadata": {
                    "ogTitle": "OG Headline Fallback",
                },
            },
        }
        mock_http.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=resp))
        )
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_headline("fallback.com")

        assert result is not None
        assert result["headline"] == "OG Headline Fallback"

    @patch("engine.clients.firecrawl.httpx.Client")
    def test_returns_none_on_failure(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 500
        mock_http.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=resp))
        )
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        assert client.get_headline("fail.com") is None

    @patch("engine.clients.firecrawl.httpx.Client")
    def test_truncates_long_headline(self, mock_http: MagicMock):
        long_headline = "A" * 300
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "success": True,
            "data": {
                "markdown": f"# {long_headline}\n\nContent.",
                "metadata": {},
            },
        }
        mock_http.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=resp))
        )
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        result = client.get_headline("long.com")

        assert result is not None
        assert len(result["headline"]) == 200

    @patch("engine.clients.firecrawl.httpx.Client")
    def test_prepends_https_to_domain(self, mock_http: MagicMock):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "success": True,
            "data": {"markdown": "# Hello", "metadata": {}},
        }
        mock_post = MagicMock(return_value=resp)
        mock_http.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=mock_post)
        )
        mock_http.return_value.__exit__ = MagicMock(return_value=False)

        client = self._make_client()
        client.get_headline("bare.com")

        # Verify the URL passed to the API has https:// prepended
        call_args = mock_post.call_args
        body = call_args[1]["json"] if "json" in call_args[1] else call_args.kwargs["json"]
        assert body["url"] == "https://bare.com"
