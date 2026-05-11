"""Read-only EmailBison campaign metrics and reply inspection.

This script never sends, approves, or mutates emails. It lists campaign details
and master-inbox replies so GTM agents can review what needs human attention.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any

from engine.clients.emailbison import EmailBisonClient
from engine.config import Settings


HIGH_INTENT_TERMS = (
    "book",
    "calendar",
    "calendly",
    "demo",
    "meet",
    "meeting",
    "interested",
    "pricing",
    "price",
    "pilot",
    "trial",
    "intro",
    "budget",
    "proposal",
)

LOW_INTENT_TERMS = (
    "unsubscribe",
    "remove me",
    "not interested",
    "no thanks",
    "out of office",
    "ooo",
    "automatic reply",
    "auto-reply",
    "vacation",
)


@dataclass
class NormalizedReply:
    id: int | str | None
    campaign_id: int | str | None
    lead_id: int | str | None
    lead_name: str
    lead_email: str
    company: str
    status: str
    folder: str
    received_at: str
    priority: str
    reason: str
    body_excerpt: str
    raw: dict[str, Any] | None = None


def _pick(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested(record: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _excerpt(text: str, limit: int = 240) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def classify_reply(record: dict[str, Any]) -> tuple[str, str]:
    body = str(_pick(record, "body", "message", "text", "plain_text", "html", "snippet") or "")
    status = str(record.get("status") or "")
    folder = str(record.get("folder") or "")
    haystack = f"{status} {folder} {body}".lower()

    low = next((term for term in LOW_INTENT_TERMS if term in haystack), None)
    if low:
        return "low", f"Low-intent signal: {low}"

    high = next((term for term in HIGH_INTENT_TERMS if term in haystack), None)
    if high or status.lower() == "interested":
        return "urgent", f"High-intent signal: {high or status}"

    return "normal", "Needs review"


def normalize_reply(record: dict[str, Any], include_raw: bool = False) -> NormalizedReply:
    lead = _nested(record, "lead", "contact", "person")
    campaign = _nested(record, "campaign")
    priority, reason = classify_reply(record)
    first = _pick(lead, "first_name", "firstName") or ""
    last = _pick(lead, "last_name", "lastName") or ""
    lead_name = str(_pick(record, "lead_name", "contact_name") or f"{first} {last}".strip())
    body = str(_pick(record, "body", "message", "text", "plain_text", "html", "snippet") or "")

    return NormalizedReply(
        id=_pick(record, "id", "reply_id"),
        campaign_id=_pick(record, "campaign_id") or _pick(campaign, "id"),
        lead_id=_pick(record, "lead_id") or _pick(lead, "id"),
        lead_name=lead_name,
        lead_email=str(_pick(record, "lead_email", "email") or _pick(lead, "email") or ""),
        company=str(_pick(record, "company") or _pick(lead, "company") or ""),
        status=str(record.get("status") or ""),
        folder=str(record.get("folder") or ""),
        received_at=str(_pick(record, "received_at", "created_at", "updated_at") or ""),
        priority=priority,
        reason=reason,
        body_excerpt=_excerpt(body),
        raw=record if include_raw else None,
    )


def _first_number(record: dict[str, Any], keys: tuple[str, ...]) -> int:
    stats = _nested(record, "stats", "analytics", "metrics")
    for source in (record, stats):
        for key in keys:
            value = source.get(key)
            if value in (None, ""):
                continue
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
    return 0


def summarize_campaign(
    campaign: dict[str, Any],
    replies: list[NormalizedReply],
) -> dict[str, Any]:
    sent = _first_number(campaign, ("sent", "sent_count", "emails_sent", "total_sent"))
    opened = _first_number(campaign, ("opened", "open_count", "opens", "total_opens"))
    clicked = _first_number(campaign, ("clicked", "click_count", "clicks", "total_clicks"))
    bounced = _first_number(campaign, ("bounced", "bounce_count", "bounces", "total_bounces"))
    urgent = sum(1 for reply in replies if reply.priority == "urgent")
    interested = sum(1 for reply in replies if reply.status.lower() == "interested")

    return {
        "id": campaign.get("id"),
        "name": campaign.get("name") or campaign.get("title") or f"Campaign {campaign.get('id')}",
        "status": campaign.get("status") or campaign.get("state"),
        "sent": sent,
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "replies": len(replies),
        "interested": interested,
        "urgent_replies": urgent,
        "reply_rate": (len(replies) / sent) if sent else None,
    }


def build_report(
    client: EmailBisonClient,
    campaign_ids: list[str],
    *,
    all_campaigns: bool = False,
    max_pages: int = 5,
    status: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    campaigns = client.get_campaigns()
    by_id = {str(c.get("id")): c for c in campaigns if c.get("id") is not None}

    selected_ids = campaign_ids
    if all_campaigns:
        selected_ids = list(by_id.keys())

    if not selected_ids:
        settings = Settings()
        selected_ids = [
            cid
            for cid in (
                settings.emailbison_campaign_id,
                settings.emailbison_listicle_campaign_id,
            )
            if cid
        ]

    campaign_reports = []
    all_replies: list[NormalizedReply] = []

    for campaign_id in selected_ids:
        campaign = client.get_campaign(campaign_id) or by_id.get(str(campaign_id), {"id": campaign_id})
        raw_replies = client.get_campaign_replies(
            campaign_id,
            status=status,
            folder="inbox",
            max_pages=max_pages,
        )
        replies = [normalize_reply(row, include_raw=include_raw) for row in raw_replies]
        all_replies.extend(replies)
        campaign_reports.append(
            {
                "campaign": summarize_campaign(campaign, replies),
                "replies": [asdict(reply) for reply in replies],
            }
        )

    urgent = sorted(
        [reply for reply in all_replies if reply.priority == "urgent"],
        key=lambda reply: reply.received_at,
        reverse=True,
    )

    return {
        "read_only": True,
        "campaigns": campaign_reports,
        "totals": {
            "campaigns": len(campaign_reports),
            "replies": len(all_replies),
            "urgent_replies": len(urgent),
            "interested_replies": sum(1 for reply in all_replies if reply.status.lower() == "interested"),
        },
        "urgent_replies": [asdict(reply) for reply in urgent[:10]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only EmailBison GTM report")
    parser.add_argument("--campaign-id", action="append", default=[], help="Campaign ID to inspect")
    parser.add_argument("--all-campaigns", action="store_true", help="Inspect every visible campaign")
    parser.add_argument("--max-pages", type=int, default=5, help="Max reply pages per campaign")
    parser.add_argument("--status", help="Optional EmailBison reply status filter")
    parser.add_argument("--include-raw", action="store_true", help="Include raw reply payloads")
    args = parser.parse_args()

    client = EmailBisonClient(Settings())
    report = build_report(
        client,
        args.campaign_id,
        all_campaigns=args.all_campaigns,
        max_pages=args.max_pages,
        status=args.status,
        include_raw=args.include_raw,
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
