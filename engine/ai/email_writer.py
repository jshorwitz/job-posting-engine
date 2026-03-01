"""OpenAI-powered personalized outreach email generation."""

from __future__ import annotations

import logging

from openai import OpenAI

from engine.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a concise, professional outreach writer for a growth marketing consultancy.
Write cold emails that are warm, specific, and under 150 words.
Never use generic phrases like "I hope this finds you well" or "I came across your company."
Reference the specific hiring signal to show you've done your research.
Always end with a clear, single call to action (e.g. "open to a 15-min call this week?").
Tone: confident but not pushy, peer-to-peer, conversational.
"""


def generate_outreach_email(
    settings: Settings,
    ceo_name: str,
    company_name: str,
    job_title_hiring: str,
    company_domain: str | None = None,
) -> tuple[str, str]:
    """Generate a personalized cold email via OpenAI.

    Args:
        settings:          App settings (API key, model).
        ceo_name:          Full name of the CEO/founder.
        company_name:      Company name.
        job_title_hiring:  The growth role they're hiring for.
        company_domain:    Company website domain (optional context).

    Returns:
        Tuple of (subject_line, email_body).
    """
    client = OpenAI(api_key=settings.openai_api_key)

    domain_context = f"\nWebsite: {company_domain}" if company_domain else ""

    prompt = f"""\
Company: {company_name}{domain_context}
CEO/Founder: {ceo_name}
Open role: {job_title_hiring}

Write a short cold email from Joel (a growth marketing expert) to {ceo_name}.
The fact that they're hiring a {job_title_hiring} signals growth ambition —
acknowledge this naturally and offer a specific, relevant insight about
scaling paid acquisition (not generic advice).

Respond with exactly two sections:
SUBJECT: <one compelling subject line>
BODY:
<email body — first-name greeting, 2-3 short paragraphs, CTA>
"""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=400,
    )

    raw = response.choices[0].message.content or ""
    subject, body = _parse_subject_body(raw)

    if not subject:
        subject = f"Re: your {job_title_hiring} hire"
    if not body:
        body = raw  # fallback to raw output

    logger.info(f"Generated email for {ceo_name} @ {company_name}: {subject}")
    return subject, body


def _parse_subject_body(raw: str) -> tuple[str, str]:
    """Parse the SUBJECT: / BODY: structured response from OpenAI."""
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
