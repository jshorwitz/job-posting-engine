"""Slack webhook client for run summaries."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


def post_run_summary(
    webhook_url: str,
    sent: int,
    skipped: int,
    failed: int,
    sample_companies: list[str] | None = None,
) -> None:
    """Post a summary message to Slack. No-ops if webhook_url is empty."""
    if not webhook_url or not webhook_url.startswith("https://"):
        return

    companies_line = ""
    if sample_companies:
        names = ", ".join(sample_companies[:5])
        companies_line = f"\n📋 Companies: {names}"

    text = (
        f"*Job Posting Growth Engine — Run Complete* :rocket:\n"
        f"✅ Sent: {sent}  |  ⏭ Skipped: {skipped}  |  ❌ Failed: {failed}"
        f"{companies_line}"
    )

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(webhook_url, json={"text": text})
            resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"Slack notification failed: {exc}")
