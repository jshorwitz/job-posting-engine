"""AI-powered listicle/podcast follow-up email generation.

Scrapes the target article with Firecrawl, extracts structured research
(tools listed, criteria, gaps), then generates a personalized follow-up
that references specific content from the article.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from openai import OpenAI
from sqlalchemy.orm import Session

from engine.clients.firecrawl import FirecrawlClient
from engine.config import Settings
from engine.db.models import ListicleTarget

logger = logging.getLogger(__name__)


def extract_research(settings: Settings, markdown: str, target: ListicleTarget) -> dict:
    """Use GPT-4o to extract structured research from article content."""
    client = OpenAI(api_key=settings.openai_api_key)

    target_type = target.target_type or "listicle"
    prompt = f"""\
Analyze this {target_type} article and extract structured data.

Article title: {target.title}
Article URL: {target.url}

Article content:
{markdown}

Return a JSON object with these fields:
- "page_kind": "listicle" or "podcast" or "guide"
- "criteria": list of evaluation criteria the article uses (e.g. ["cross-platform support", "ease of use", "pricing"])
- "mentioned_tools": list of tool/product names mentioned in the article (just names, max 15)
- "summary": 1-2 sentence summary of what the article covers and who it targets
- "gap": what's missing from this list that Synter could fill (Synter is an AI agent platform that manages ad campaigns across 7 platforms — Google, Meta, LinkedIn, Reddit, X, TikTok, Microsoft — from a single chat interface, no dashboard, the AI agent handles full campaign lifecycle)

Return ONLY valid JSON, no markdown fences."""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You analyze articles and return structured JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=600,
    )

    raw = response.choices[0].message.content or "{}"
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse research JSON for {target.url}")
        return {"summary": raw[:300], "mentioned_tools": [], "criteria": [], "gap": ""}


def generate_followup_email(
    settings: Settings,
    target: ListicleTarget,
    research: dict,
    step: str,
) -> tuple[str, str]:
    """Generate a personalized follow-up email using article research.

    Args:
        step: "follow_up_1" or "follow_up_2"

    Returns:
        Tuple of (subject, body).
    """
    client = OpenAI(api_key=settings.openai_api_key)

    editor_first = (target.editor_name or "").split()[0] if target.editor_name else "there"
    tools_str = ", ".join(research.get("mentioned_tools", [])[:5]) or "various tools"
    criteria_str = ", ".join(research.get("criteria", [])[:3]) or "the criteria you evaluated"
    gap = research.get("gap", "")
    summary = research.get("summary", "")

    if target.target_type == "podcast":
        context = f"""This is a follow-up to a podcast guest pitch. The podcast is "{target.title}".
Article summary: {summary}
The editor's name is {editor_first}."""
        synter_pitch = "AI agents are replacing the $400B ad agency model. Synter manages campaigns across 7 ad platforms from a single chat interface."
    else:
        context = f"""This is a follow-up to a listicle placement request. The article is "{target.title}" on {target.domain}.
It currently mentions: {tools_str}
It evaluates tools on: {criteria_str}
Gap Synter fills: {gap}
Article summary: {summary}"""
        synter_pitch = "Synter is an AI agent platform that manages ad campaigns across Google, Meta, LinkedIn, Reddit, X, TikTok, and Microsoft Ads from a single chat interface. No dashboard, no manual setup."

    urgency = "This is follow-up #1 (3 days after initial email)." if step == "follow_up_1" else "This is the final follow-up (6 days after initial email). Keep it brief and respectful."

    prompt = f"""\
{context}

{urgency}

Synter pitch: {synter_pitch}

Write a short follow-up email from Joel (founder of Synter) to {editor_first}.

RULES:
- Reference 1-2 specific tools from their article to show you actually read it
- Explain concretely why Synter belongs alongside those tools (don't just say "we're different")
- NO emojis. None. Zero.
- NO em dashes (—). Use periods or commas instead.
- NO buzzwords (leverage, unlock, game-changer, revolutionize, seamless, cutting-edge, streamline, elevate)
- Under 80 words
- Casual, peer-to-peer tone
- End with a low-friction CTA
- Sign off as Joel

Respond with exactly:
SUBJECT: <subject line>
BODY:
<email text>"""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You write short, compelling follow-up emails. No fluff."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=300,
    )

    raw = response.choices[0].message.content or ""
    subject, body = _parse_subject_body(raw)

    if not subject:
        subject = f"Re: Adding Synter to your article"
    if not body:
        body = raw

    logger.info(f"Generated {step} for {target.editor_email}: {subject}")
    return subject, body


def get_or_create_research(
    session: Session,
    settings: Settings,
    target: ListicleTarget,
) -> dict | None:
    """Load cached research or scrape + extract fresh research.

    Returns research dict or None if scraping/extraction fails.
    """
    # Use cached research if available
    if target.research_json:
        try:
            return json.loads(target.research_json)
        except json.JSONDecodeError:
            pass

    # Scrape the article
    try:
        firecrawl = FirecrawlClient(settings)
    except ValueError:
        logger.warning("FIRECRAWL_API_KEY not set — cannot research articles")
        return None

    scraped = firecrawl.scrape_url(target.url)
    if not scraped or not scraped.get("markdown"):
        target.research_error = "Scrape returned no content"
        session.commit()
        logger.warning(f"No content scraped for {target.url}")
        return None

    # Extract structured research
    research = extract_research(settings, scraped["markdown"], target)

    # Cache it
    target.research_json = json.dumps(research)
    target.researched_at = datetime.now(timezone.utc)
    target.research_error = None
    session.commit()

    logger.info(
        f"Research cached for {target.domain}: "
        f"{len(research.get('mentioned_tools', []))} tools, "
        f"{len(research.get('criteria', []))} criteria"
    )
    return research


def _parse_subject_body(raw: str) -> tuple[str, str]:
    """Parse SUBJECT: / BODY: structured response."""
    subject = ""
    body_lines: list[str] = []
    in_body = False

    for line in raw.strip().splitlines():
        if line.strip().upper().startswith("SUBJECT:"):
            subject = line.split(":", 1)[1].strip()
        elif line.strip().upper().startswith("BODY:"):
            in_body = True
        elif in_body:
            body_lines.append(line)

    return subject, "\n".join(body_lines).strip()
