#!/usr/bin/env python3
"""Daily outbound campaign report — sent via Loops.so transactional email.

Pulls stats from all active Smartlead campaigns and sends a summary
to the configured recipient.

Usage:
    python scripts/daily_report.py
    python scripts/daily_report.py --to joel@synterai.com
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_report")

SMARTLEAD_API = "https://server.smartlead.ai/api/v1"
LOOPS_API = "https://app.loops.so/api/v1"

# Geo campaign IDs
GEO_CAMPAIGNS = {
    "Americas (US/CA)": os.environ.get("SMARTLEAD_CAMPAIGN_ID_AMERICAS", "3070911"),
    "EU (UK/DE/NL/FR/IE)": os.environ.get("SMARTLEAD_CAMPAIGN_ID_EU", "3070909"),
    "APAC (AU/NZ)": os.environ.get("SMARTLEAD_CAMPAIGN_ID_APAC", "3070910"),
}

# Also check the legacy campaigns
LEGACY_CAMPAIGNS = {
    "Growth Machines Webinar": "3068409",
    "CSS List (Pilot)": "3051980",
    "US Marketing Agencies": "2835081",
}


def get_campaign_stats(api_key: str, campaign_id: str) -> dict:
    """Fetch campaign stats from Smartlead."""
    try:
        # Get campaign info
        info_resp = httpx.get(
            f"{SMARTLEAD_API}/campaigns/{campaign_id}",
            params={"api_key": api_key},
            timeout=10,
        )
        info = info_resp.json() if info_resp.status_code == 200 else {}

        # Get lead count
        leads_resp = httpx.get(
            f"{SMARTLEAD_API}/campaigns/{campaign_id}/leads",
            params={"api_key": api_key, "offset": 0, "limit": 1},
            timeout=10,
        )
        leads_data = leads_resp.json() if leads_resp.status_code == 200 else {}

        # Get statistics
        stats_resp = httpx.get(
            f"{SMARTLEAD_API}/campaigns/{campaign_id}/statistics",
            params={"api_key": api_key},
            timeout=15,
        )
        stats_data = stats_resp.json() if stats_resp.status_code == 200 else {}
        records = stats_data.get("data", [])

        sent = len([r for r in records if r.get("sent_time")])
        replied = len([r for r in records if r.get("reply_time")])
        bounced = len([r for r in records if r.get("is_bounced")])

        return {
            "status": info.get("status", "?"),
            "total_leads": leads_data.get("total_leads", "?"),
            "sent": sent,
            "replied": replied,
            "bounced": bounced,
            "reply_rate": f"{(replied / sent * 100):.1f}%" if sent > 0 else "0%",
        }
    except Exception as e:
        return {"error": str(e)}


def _bar(value: int, max_val: int, width: int = 20) -> str:
    """Render a simple ASCII progress bar."""
    if max_val <= 0:
        return "[" + " " * width + "]"
    filled = min(int(value / max_val * width), width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def _status_icon(status: str) -> str:
    icons = {"ACTIVE": "▶", "PAUSED": "⏸", "STOPPED": "■", "DRAFTED": "○", "COMPLETED": "✓"}
    return icons.get(status, "?")


def build_report(api_key: str) -> str:
    """Build the daily report in ANSI/terminal style."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%a %b %d, %Y")
    time_str = now.strftime("%H:%M UTC")

    lines = [
        "┌──────────────────────────────────────────────────┐",
        "│          SYNTER GROWTH ENGINE                    │",
        "│          Daily Operations Report                 │",
        f"│          {date_str:>28}          │",
        "└──────────────────────────────────────────────────┘",
        "",
    ]

    total_leads = 0
    total_sent = 0
    total_replied = 0
    total_bounced = 0

    # Geo campaigns
    lines.append("┌─ GEO CAMPAIGNS ─────────────────────────────────┐")

    for name, cid in GEO_CAMPAIGNS.items():
        stats = get_campaign_stats(api_key, cid)
        if "error" in stats:
            lines.append(f"│  {name}: ERROR")
            continue

        leads = stats.get("total_leads", 0)
        sent = stats.get("sent", 0)
        replied = stats.get("replied", 0)
        bounced = stats.get("bounced", 0)
        status = stats.get("status", "?")
        reply_rate = stats.get("reply_rate", "0%")

        leads_int = int(leads) if isinstance(leads, (int, str)) and str(leads).isdigit() else 0
        total_leads += leads_int
        total_sent += sent
        total_replied += replied
        total_bounced += bounced

        lines.extend([
            "│",
            f"│  {_status_icon(status)} {name}",
            f"│    Leads: {leads_int:<6}  Sent: {sent:<6}  Replied: {replied:<4}  Bounced: {bounced}",
            f"│    Reply rate: {reply_rate}  {_bar(replied, sent if sent > 0 else 1, 15)}",
        ])

    lines.extend([
        "│",
        "├──────────────────────────────────────────────────┤",
        f"│  TOTAL: {total_leads} leads │ {total_sent} sent │ {total_replied} replied │ {total_bounced} bounced",
        f"│  Reply rate: {(total_replied / total_sent * 100):.1f}%" if total_sent > 0 else "│  Reply rate: 0%",
        "└──────────────────────────────────────────────────┘",
        "",
    ])

    # Legacy campaigns
    lines.append("┌─ LEGACY CAMPAIGNS ──────────────────────────────┐")
    for name, cid in LEGACY_CAMPAIGNS.items():
        stats = get_campaign_stats(api_key, cid)
        if "error" in stats:
            continue
        status = stats.get("status", "?")
        leads = stats.get("total_leads", "?")
        sent = stats.get("sent", 0)
        replied = stats.get("replied", 0)
        rate = stats.get("reply_rate", "0%")
        lines.append(f"│  {_status_icon(status)} {name:<30} {leads:>5} leads  {sent:>4} sent  {replied:>3} replied  {rate:>5}")

    lines.extend([
        "└──────────────────────────────────────────────────┘",
        "",
    ])

    # Pipeline status
    lines.extend([
        "┌─ PIPELINE ───────────────────────────────────────┐",
        "│  Discovery:  Mon-Fri 8am ET  (38 countries)      │",
        "│  Signals:    Hiring + Fundraising + Tech stack    │",
        "│  Enrichment: Hunter + SpyFu + BuiltWith + OpenAI │",
        "│  Sending:    Smartlead (51 accounts, plain text)  │",
        "│  CRM:        Attio (webhook auto-sync)           │",
        "│  Audiences:  Google Ads + Meta (758 emails)      │",
        "└──────────────────────────────────────────────────┘",
        "",
        f"  Report generated {time_str}",
        "",
        "  ┌───┐",
        "  │ ◉ │  Synter Growth Engine",
        "  │ ▽ │  syntermedia.ai",
        "  └───┘",
    ])

    return "\n".join(lines)


def send_via_loops(report: str, to_email: str) -> bool:
    """Send report via Loops.so transactional email."""
    loops_key = os.environ.get("LOOPS_API_KEY", "")
    if not loops_key:
        logger.warning("LOOPS_API_KEY not set, printing report to stdout instead")
        print(report)
        return False

    try:
        resp = httpx.post(
            f"{LOOPS_API}/transactional",
            headers={
                "Authorization": f"Bearer {loops_key}",
                "Content-Type": "application/json",
            },
            json={
                "transactionalId": os.environ.get("LOOPS_REPORT_TEMPLATE_ID", ""),
                "email": to_email,
                "dataVariables": {
                    "reportBody": report.replace("\n", "<br>"),
                    "reportDate": datetime.now(timezone.utc).strftime("%B %d, %Y"),
                },
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            logger.info(f"Report sent to {to_email} via Loops")
            return True
        else:
            logger.warning(f"Loops send failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Loops error: {e}")

    # Fallback: print to stdout (Railway logs)
    print(report)
    return False


def send_via_gmail(report: str, to_email: str) -> bool:
    """Fallback: send via Gmail SMTP."""
    import smtplib
    from email.mime.text import MIMEText

    gmail_pass = os.environ.get("GMAIL_APP_PASS", "")
    from_email = os.environ.get("GMAIL_FROM", "joel@synterai.com")

    if not gmail_pass:
        logger.warning("GMAIL_APP_PASS not set")
        print(report)
        return False

    msg = MIMEText(report)
    msg["Subject"] = f"Growth Engine Report — {datetime.now(timezone.utc).strftime('%b %d')}"
    msg["From"] = from_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(from_email, gmail_pass)
            server.sendmail(from_email, to_email, msg.as_string())
        logger.info(f"Report sent to {to_email} via Gmail")
        return True
    except Exception as e:
        logger.error(f"Gmail error: {e}")
        print(report)
        return False


def main():
    parser = argparse.ArgumentParser(description="Daily outbound report")
    parser.add_argument("--to", default="joel@synterai.com", help="Recipient email")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout only")
    args = parser.parse_args()

    api_key = os.environ.get("SMARTLEAD_API_KEY", "")
    if not api_key:
        logger.error("SMARTLEAD_API_KEY not set")
        sys.exit(1)

    report = build_report(api_key)

    if args.stdout:
        print(report)
        return

    # Try Loops first, fall back to Gmail
    if not send_via_loops(report, args.to):
        send_via_gmail(report, args.to)


if __name__ == "__main__":
    main()
