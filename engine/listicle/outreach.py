"""Listicle outreach — send placement request emails to article editors.

3-email sequence adapted from the Above Apex listicle guide:
  1. Initial request (short, specific)
  2. Follow-up with incentive offer (3 days later)
  3. Final follow-up (6 days later)

Usage:
    python -m engine.listicle.outreach --send
    python -m engine.listicle.outreach --send --dry-run
    python -m engine.listicle.outreach --status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

import httpx

from engine.config import Settings
from engine.db.database import init_db
from engine.db.models import ListicleTarget, ListicleStatus

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SMARTLEAD_API_BASE = "https://server.smartlead.ai/api/v1"


# Email templates for the 3-step sequence
TEMPLATES = {
    "initial": {
        "subject": "Adding Synter to your {article_type} article?",
        "body": """Hi {editor_first_name},

Joel from Synter here.

I just read your article "{article_title}" — great roundup.

Would you be open to adding Synter to the list?

We're an AI agent platform that manages ad campaigns across 7 platforms (Google, Meta, LinkedIn, Reddit, X, TikTok, Microsoft) from a single chat interface. No dashboard, no manual campaign setup — the AI agent handles the full lifecycle.

If you see the fit, I'm happy to write the excerpt for you or set up a free trial so you can test it yourself.

Open to creating a win-win situation — let me know.

Best,
Joel Horwitz
Founder, Synter
syntermedia.ai""",
    },
    "follow_up_1": {
        "subject": "Re: Adding Synter to your article",
        "body": """Hi {editor_first_name},

Just following up on my previous email about your article:

{article_url}

Synter is the go-to AI agent platform for cross-platform ad management — used by teams running campaigns across Google, Meta, LinkedIn, and more.

I'm open to creating a win-win and can offer:

- Free extended trial for your readers
- A backlink to your article from our site
- Writing the full product description/excerpt myself

Would love to discuss.

Best,
Joel""",
    },
    "follow_up_2": {
        "subject": "Re: Synter + your article — one last note",
        "body": """Hey {editor_first_name},

One last follow-up on adding Synter to your article.

Our platform is directly relevant — we're one of the leading AI agent solutions for ad management, and we're actively used by teams managing campaigns across 7 platforms.

Happy to make it easy: I can send over a ready-to-publish excerpt with screenshots, or hop on a quick call.

Open to discussing this?

Best,
Joel""",
    },
}

PODCAST_TEMPLATES = {
    "initial": {
        "subject": "Guest pitch: AI agents replacing ad agencies",
        "body": """Hi {editor_first_name},

Joel Horwitz here — founder of Synter (syntermedia.ai).

{podcast_intro}

The pitch: AI agents are starting to replace the $400B ad agency model. Not by generating ad copy — by actually executing full campaign lifecycles across Google, Meta, LinkedIn, Reddit, TikTok, X, and Microsoft Ads from a single chat interface.

We built Synter to do exactly this. Some talking points I could cover:

- Why cross-platform is the real moat (every platform's AI only optimizes for its own inventory)
- The 90-day agency failure arc and why AI agents avoid it
- How we went from zero to managing campaigns across 7 platforms in 3 months
- The MCP protocol and why every ad tool will need one

I'm a technical founder who can go deep on the engineering and the business side. Happy to tailor the conversation to what resonates with your listeners.

Would you be open to having me on?

Best,
Joel Horwitz
Founder, Synter
syntermedia.ai""",
    },
    "follow_up_1": {
        "subject": "Re: Guest pitch for your podcast",
        "body": """Hi {editor_first_name},

Following up on my guest pitch regarding "{article_title}".

Quick context: Synter is an AI agent platform that manages ad campaigns across 7 platforms from chat. We're live with paying customers and growing fast.

I think the story of building AI agents that replace $15K/month agency retainers would resonate with your audience. Happy to do a short pre-call to align on topics.

Open to it?

Best,
Joel""",
    },
    "follow_up_2": {
        "subject": "Re: Guest pitch — last note",
        "body": """Hey {editor_first_name},

One last follow-up on the guest pitch for your show.

We just crossed 100 campaigns managed by AI agents across 7 ad platforms — the story of how we got here in 3 months is pretty wild.

Happy to make it easy: I can send over a one-pager with talking points, or jump on a 5-minute pre-call.

Either way, no hard feelings if the timing isn't right.

Best,
Joel""",
    },
}

# Domains that host actual podcasts (not articles about podcasts)
_PODCAST_HOSTING_DOMAINS = {
    "open.spotify.com", "podcasts.apple.com", "podcast.app",
    "podbean.com", "anchor.fm", "buzzsprout.com", "transistor.fm",
    "simplecast.com", "megaphone.fm", "podomatic.com",
}


def _render_template(template: dict, target: ListicleTarget) -> dict:
    """Render email template with target data."""
    editor_first = (target.editor_name or "").split()[0] if target.editor_name else "there"

    # Detect article type from title
    title_lower = (target.title or "").lower()
    if "best" in title_lower:
        article_type = "best-of"
    elif "top" in title_lower:
        article_type = "top picks"
    else:
        article_type = "roundup"

    # For podcasts: detect if it's an actual podcast or a listicle about podcasts
    podcast_intro = ""
    if target.target_type == "podcast":
        is_listicle_about_podcasts = any(
            kw in title_lower for kw in ["best", "top ", "10 ", "12 ", "15 ", "20 ", "25 ", "30 ", "35 "]
        )
        is_actual_podcast = (
            target.domain in _PODCAST_HOSTING_DOMAINS
            or (not is_listicle_about_podcasts and "podcast" in title_lower)
        )
        if is_actual_podcast:
            podcast_intro = f'I came across your podcast "{target.title}" and think your audience would love a conversation about what\'s happening with AI agents in advertising right now.'
        else:
            podcast_intro = f'I saw your article "{target.title}" and noticed you cover marketing podcasts. I\'d love to be featured — I think your readers would find the story of AI agents replacing ad agencies genuinely interesting.'

    replacements = {
        "{editor_first_name}": editor_first,
        "{article_title}": target.title or "",
        "{article_url}": target.url or "",
        "{article_type}": article_type,
        "{podcast_intro}": podcast_intro,
    }

    subject = template["subject"]
    body = template["body"]
    for key, value in replacements.items():
        subject = subject.replace(key, value)
        body = body.replace(key, value)

    return {"subject": subject, "body": body}


def _send_via_smartlead(
    settings: Settings,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    company_name: str = "",
) -> bool:
    """Add lead to Smartlead campaign for warmed-up sending."""
    from engine.outreach.smartlead_sender import send_email as smartlead_send
    campaign_id = settings.smartlead_listicle_campaign_id or settings.smartlead_campaign_id
    return smartlead_send(
        settings=settings,
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body=body,
        company_name=company_name,
        campaign_id_override=campaign_id,
    )


def _send_email(settings: Settings, to_email: str, to_name: str, subject: str, body: str, company_name: str = "") -> bool:
    """Send via SMTP/Gmail (preferred) → Smartlead → Resend (fallback)."""
    if settings.smtp_user and settings.smtp_pass and settings.from_email:
        from engine.outreach.smtp_sender import send_email as smtp_send
        return smtp_send(settings=settings, to_email=to_email, to_name=to_name, subject=subject, body=body)
    if settings.smartlead_api_key and (settings.smartlead_listicle_campaign_id or settings.smartlead_campaign_id):
        return _send_via_smartlead(settings, to_email, to_name, subject, body, company_name)
    return _send_via_resend(settings, to_email, subject, body)


def _send_via_resend(settings: Settings, to_email: str, subject: str, body: str) -> bool:
    """Send an email via Resend API (fallback if EmailBison not configured).

    Emails sent outside business hours (8am-6pm PT, Mon-Fri) are automatically
    scheduled for the next business morning at 9:15am PT.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    # Convert plain text to simple HTML
    html_body = body.replace("\n", "<br>")

    payload = {
        "from": f"Joel Horwitz <{settings.resend_from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "reply_to": settings.resend_from_email,
    }

    # Schedule for business hours if sending outside 8am-6pm PT Mon-Fri
    pt = ZoneInfo("America/Los_Angeles")
    now_pt = datetime.now(pt)
    hour, weekday = now_pt.hour, now_pt.weekday()
    if hour < 8 or hour >= 18 or weekday >= 5:
        # Find next business day at 9:15am PT
        next_send = now_pt.replace(hour=9, minute=15, second=0, microsecond=0)
        if hour >= 8:
            next_send += timedelta(days=1)
        while next_send.weekday() >= 5:
            next_send += timedelta(days=1)
        payload["scheduled_at"] = next_send.isoformat()
        logger.info(f"Resend: outside business hours, scheduling for {next_send.strftime('%a %b %d %I:%M%p PT')}")

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info(f"Resend: sent to {to_email} (id={data.get('id', '')})")
            return True

        logger.error(f"Resend: {resp.status_code} — {resp.text[:200]}")
        return False

    except Exception as e:
        logger.error(f"Resend: failed for {to_email} — {e}")
        return False


def send_outreach(
    session, settings: Settings, dry_run: bool = False, limit: int = 10,
    target_type: str | None = None,
) -> dict:
    """Send initial outreach emails to editors/hosts with CONTACT_FOUND status."""
    query = (
        session.query(ListicleTarget)
        .filter(ListicleTarget.status == ListicleStatus.CONTACT_FOUND)
        .filter(ListicleTarget.editor_email.isnot(None))
    )
    if target_type:
        query = query.filter(ListicleTarget.target_type == target_type)
    targets = query.limit(limit).all()

    stats = {"sent": 0, "failed": 0, "skipped": 0}

    for target in targets:
        templates = PODCAST_TEMPLATES if target.target_type == "podcast" else TEMPLATES
        rendered = _render_template(templates["initial"], target)

        if dry_run:
            print(f"[DRY RUN] To: {target.editor_email} | {rendered['subject']}")
            print(f"  Article: {target.title[:60]}")
            print(f"  Domain: {target.domain}")
            print()
            stats["sent"] += 1
            continue

        success = _send_email(
            settings=settings,
            to_email=target.editor_email,
            to_name=target.editor_name or "",
            subject=rendered["subject"],
            body=rendered["body"],
            company_name=target.domain or "",
        )

        if success:
            target.status = ListicleStatus.OUTREACH_SENT
            target.outreach_sent_at = datetime.now(timezone.utc)
            session.commit()
            stats["sent"] += 1
            logger.info(f"Outreach sent: {target.editor_email} — {target.title[:50]}")
        else:
            stats["failed"] += 1
            logger.error(f"Outreach failed: {target.editor_email}")

    return stats


FOLLOWUP_DELAYS = {
    ListicleStatus.OUTREACH_SENT: (ListicleStatus.FOLLOW_UP_1, 2),   # 2 days after initial
    ListicleStatus.FOLLOW_UP_1: (ListicleStatus.FOLLOW_UP_2, 3),     # 3 days after follow-up 1
}


def send_followups(session, settings: Settings, dry_run: bool = False, limit: int = 20) -> dict:
    """Send follow-up emails to targets that haven't responded after N days.

    Enriches each target with article research (via Firecrawl + GPT-4o) to
    generate personalized follow-ups. Falls back to static templates if
    scraping or AI generation fails.

    Checks outreach_sent_at timestamps and advances:
      OUTREACH_SENT → FOLLOW_UP_1 (after 3 days)
      FOLLOW_UP_1   → FOLLOW_UP_2 (after 3 more days)
    """
    from engine.listicle.followup_writer import generate_followup_email, get_or_create_research

    now = datetime.now(timezone.utc)
    stats = {"follow_up_1_sent": 0, "follow_up_2_sent": 0, "failed": 0, "not_due": 0, "researched": 0}

    for current_status, (next_status, delay_days) in FOLLOWUP_DELAYS.items():
        cutoff = now - timedelta(days=delay_days)

        targets = (
            session.query(ListicleTarget)
            .filter(ListicleTarget.status == current_status)
            .filter(ListicleTarget.editor_email.isnot(None))
            .filter(ListicleTarget.outreach_sent_at <= cutoff)
            .limit(limit)
            .all()
        )

        for target in targets:
            template_key = "follow_up_1" if next_status == ListicleStatus.FOLLOW_UP_1 else "follow_up_2"

            # Try enriched AI-generated follow-up
            subject, body = None, None
            research = get_or_create_research(session, settings, target)
            if research:
                stats["researched"] += 1
                try:
                    subject, body = generate_followup_email(
                        settings=settings,
                        target=target,
                        research=research,
                        step=template_key,
                    )
                except Exception as e:
                    logger.warning(f"AI follow-up generation failed for {target.editor_email}: {e}")

            # Fallback to static template
            if not subject or not body:
                if target.target_type == "podcast":
                    template_set = PODCAST_TEMPLATES
                else:
                    template_set = TEMPLATES
                template = template_set.get(template_key)
                if not template:
                    logger.debug(f"No {template_key} template for {target.target_type}, skipping {target.editor_email}")
                    stats["not_due"] += 1
                    continue
                rendered = _render_template(template, target)
                subject, body = rendered["subject"], rendered["body"]
                logger.info(f"Using static template for {target.editor_email} (research unavailable)")

            if dry_run:
                enriched_tag = "✨ ENRICHED" if research else "📝 STATIC"
                print(f"[DRY RUN] [{enriched_tag}] {template_key} → {target.editor_email}")
                print(f"  Subject: {subject}")
                print(f"  Sent initial: {target.outreach_sent_at.strftime('%Y-%m-%d') if target.outreach_sent_at else '?'}")
                print(f"  Article: {target.title[:60]}")
                if research:
                    tools = research.get("mentioned_tools", [])[:5]
                    print(f"  Tools found: {', '.join(tools) if tools else 'none'}")
                print(f"  Body preview: {body[:120]}...")
                print()
                stats[f"{template_key}_sent"] += 1
                continue

            success = _send_email(
                settings=settings,
                to_email=target.editor_email,
                to_name=target.editor_name or "",
                subject=subject,
                body=body,
                company_name=target.domain or "",
            )

            if success:
                target.status = next_status
                target.outreach_sent_at = now  # reset timer for next follow-up
                session.commit()
                stats[f"{template_key}_sent"] += 1
                logger.info(f"{template_key} sent: {target.editor_email} — {target.title[:50]}")
            else:
                stats["failed"] += 1
                logger.error(f"{template_key} failed: {target.editor_email}")

    return stats


def show_status(session) -> None:
    """Show outreach pipeline status."""
    from sqlalchemy import func as sqla_func

    counts = (
        session.query(ListicleTarget.status, sqla_func.count(ListicleTarget.id))
        .group_by(ListicleTarget.status)
        .all()
    )

    status_map = {s.value: c for s, c in counts}
    total = sum(status_map.values())

    print(f"\n{'='*50}")
    print(f"  Listicle Outreach Pipeline Status")
    print(f"{'='*50}")
    print(f"  ⬜ Discovered:     {status_map.get('discovered', 0)}")
    print(f"  👤 Contact Found:  {status_map.get('contact_found', 0)}")
    print(f"  📧 Outreach Sent:  {status_map.get('outreach_sent', 0)}")
    print(f"  📧 Follow-up 1:    {status_map.get('follow_up_1', 0)}")
    print(f"  📧 Follow-up 2:    {status_map.get('follow_up_2', 0)}")
    print(f"  ✅ Listed:         {status_map.get('listed', 0)}")
    print(f"  ❌ Rejected:       {status_map.get('rejected', 0)}")
    print(f"  😶 No Response:    {status_map.get('no_response', 0)}")
    print(f"  ─────────────────────────────")
    print(f"  Total:             {total}")
    print()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Listicle outreach emails")
    parser.add_argument("--send", action="store_true", help="Send outreach to editors with contacts")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("--limit", type=int, default=10, help="Max emails to send")
    args = parser.parse_args()

    settings = Settings()
    SessionFactory = init_db(settings.database_path)
    session = SessionFactory()

    if args.status:
        show_status(session)
        return

    if args.send:
        if not settings.resend_api_key:
            print(json.dumps({"success": False, "error": "RESEND_API_KEY not set"}))
            sys.exit(1)
        stats = send_outreach(session, settings, dry_run=args.dry_run, limit=args.limit)
        print(json.dumps({"success": True, "dry_run": args.dry_run, **stats}, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
