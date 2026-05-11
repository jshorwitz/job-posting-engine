"""Read-only Smartlead campaign metrics and reply inspection."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from html import unescape
from typing import Any

import httpx

from engine.config import Settings

SMARTLEAD_API_BASE = "https://server.smartlead.ai/api/v1"

HIGH_INTENT_TERMS = ("yes", "interested", "demo", "meeting", "pricing", "pilot", "trial")
LOW_INTENT_TERMS = (
    "unsubscribe",
    "stop",
    "remove me",
    "not interested",
    "no longer available",
    "out of office",
    "automatic reply",
)
REFERRAL_TERMS = ("contact ", "reach out to", "business inquiries", "please contact")


@dataclass
class SmartleadReply:
    campaign_id: int | str | None
    campaign_name: str
    lead_name: str
    lead_email: str
    reply_time: str
    priority: str
    reason: str
    reply_excerpt: str
    stats_id: str | None


def html_to_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = re.sub(r"</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split())


def latest_reply_message(message: dict[str, Any]) -> dict[str, Any]:
    history = message.get("email_history") or []
    replies = [item for item in history if str(item.get("type", "")).upper() == "REPLY"]
    if not replies:
        return {}
    return sorted(replies, key=lambda item: str(item.get("time") or ""), reverse=True)[0]


def classify_reply(text: str) -> tuple[str, str]:
    lowered = text.lower()
    hard_low = next((term for term in LOW_INTENT_TERMS[:4] if term in lowered), None)
    if hard_low:
        return "low", f"Low-intent signal: {hard_low}"
    referral = next((term for term in REFERRAL_TERMS if term in lowered), None)
    if referral:
        return "normal", f"Referral/routing signal: {referral.strip()}"
    low = next((term for term in LOW_INTENT_TERMS if term in lowered), None)
    if low:
        return "low", f"Low-intent signal: {low}"
    high = next((term for term in HIGH_INTENT_TERMS if term in lowered), None)
    if high:
        return "urgent", f"High-intent signal: {high}"
    return "normal", "Needs review"


def normalize_reply(message: dict[str, Any]) -> SmartleadReply:
    reply = latest_reply_message(message)
    body = html_to_text(str(reply.get("email_body") or ""))
    priority, reason = classify_reply(body)
    lead_name = " ".join(
        part
        for part in (
            str(message.get("lead_first_name") or "").strip(),
            str(message.get("lead_last_name") or "").strip(),
        )
        if part
    )
    return SmartleadReply(
        campaign_id=message.get("email_campaign_id"),
        campaign_name=str(message.get("email_campaign_name") or ""),
        lead_name=lead_name,
        lead_email=str(message.get("lead_email") or ""),
        reply_time=str(message.get("last_reply_time") or reply.get("time") or ""),
        priority=priority,
        reason=reason,
        reply_excerpt=body[:300],
        stats_id=reply.get("stats_id"),
    )


class SmartleadReadOnlyClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("SMARTLEAD_API_KEY is required")
        self.api_key = api_key

    def get_campaign_statistics(self, campaign_id: str, limit: int = 1000) -> dict[str, Any]:
        response = httpx.get(
            f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/statistics",
            params={"api_key": self.api_key, "offset": 0, "limit": limit},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_inbox_replies(self, campaign_ids: list[str], limit: int = 50) -> list[dict[str, Any]]:
        response = httpx.post(
            f"{SMARTLEAD_API_BASE}/master-inbox/inbox-replies",
            params={"api_key": self.api_key, "fetch_message_history": "true"},
            json={
                "offset": 0,
                "limit": limit,
                "filters": {
                    "emailStatus": "Replied",
                    "campaignId": [int(campaign_id) for campaign_id in campaign_ids],
                },
                "sortBy": "REPLY_TIME_DESC",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("data", [])


def campaign_metrics(statistics: dict[str, Any]) -> dict[str, Any]:
    rows = statistics.get("data") or []
    sent = sum(1 for row in rows if row.get("sent_time"))
    replied = sum(1 for row in rows if row.get("reply_time"))
    bounced = sum(1 for row in rows if row.get("is_bounced"))
    opened = sum(1 for row in rows if row.get("open_time") or int(row.get("open_count") or 0) > 0)
    clicked = sum(1 for row in rows if row.get("click_time") or int(row.get("click_count") or 0) > 0)
    return {
        "records": len(rows),
        "sent": sent,
        "opened": opened,
        "clicked": clicked,
        "replied": replied,
        "bounced": bounced,
        "reply_rate": (replied / sent) if sent else None,
        "bounce_rate": (bounced / sent) if sent else None,
    }


def build_report(
    client: SmartleadReadOnlyClient,
    campaign_ids: list[str],
    *,
    limit: int = 50,
) -> dict[str, Any]:
    metrics = {
        campaign_id: campaign_metrics(client.get_campaign_statistics(campaign_id))
        for campaign_id in campaign_ids
    }
    replies = [normalize_reply(row) for row in client.get_inbox_replies(campaign_ids, limit=limit)]
    urgent = [reply for reply in replies if reply.priority == "urgent"]
    normal = [reply for reply in replies if reply.priority == "normal"]
    low = [reply for reply in replies if reply.priority == "low"]
    return {
        "read_only": True,
        "campaign_ids": campaign_ids,
        "metrics": metrics,
        "totals": {
            "replies": len(replies),
            "urgent_replies": len(urgent),
            "normal_replies": len(normal),
            "low_replies": len(low),
        },
        "urgent_replies": [asdict(reply) for reply in urgent],
        "replies": [asdict(reply) for reply in replies],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Smartlead GTM report")
    parser.add_argument("--campaign-id", action="append", default=[], help="Campaign ID to inspect")
    parser.add_argument("--limit", type=int, default=50, help="Reply limit")
    args = parser.parse_args()

    settings = Settings()
    campaign_ids = args.campaign_id or [
        cid
        for cid in (settings.smartlead_campaign_id, settings.smartlead_listicle_campaign_id)
        if cid
    ]
    if not campaign_ids:
        raise SystemExit("No Smartlead campaign IDs configured")

    client = SmartleadReadOnlyClient(settings.smartlead_api_key)
    print(json.dumps(build_report(client, campaign_ids, limit=args.limit), indent=2, default=str))


if __name__ == "__main__":
    main()
