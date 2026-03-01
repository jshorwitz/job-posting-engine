"""OpenAI-powered personalized outreach email generation."""

from __future__ import annotations

import logging

from openai import OpenAI

from engine.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You write cold emails that read like a real person typed them in Gmail. Short, direct, no fluff.

ABSOLUTE RULES:
- NO emojis. None.
- NO em dashes. Use periods or commas.
- NO exclamation marks (one max in entire email).
- NO words like: leverage, unlock, game-changer, cutting-edge, streamline, elevate,
  supercharge, revolutionize, next-level, synergy, robust, seamless, holistic, innovative.
- NO "I hope this finds you well", "I came across your company", "I'd love to connect".
- NO bullet points or numbered lists. Write like a person, not a pitch deck.
- Keep it under 100 words. 4-5 sentences max.

WHAT TO SAY:
- Mention the specific job posting (role title) as the reason you're reaching out.
- Explain how {company_name} {company_pitch}, so they can get results fast without
  waiting for the new hire to ramp up.
- One clear CTA: a short call this week.
- Sign off as {sender_name}.

Tone: casual, peer-to-peer, like texting a colleague. Lowercase subject line preferred.
"""


def generate_outreach_email(
    settings: Settings,
    ceo_name: str,
    company_name: str,
    job_title_hiring: str,
    company_domain: str | None = None,
) -> tuple[str, str]:
    """Generate a personalized cold email via OpenAI.

    Returns:
        Tuple of (subject_line, email_body).
    """
    client = OpenAI(api_key=settings.openai_api_key)

    domain_context = f"\nWebsite: {company_domain}" if company_domain else ""
    first_name = ceo_name.split()[0] if ceo_name else "there"
    sender = settings.sender_name or "there"

    system = SYSTEM_PROMPT.format(
        company_name=settings.company_name or "our company",
        company_pitch=settings.company_pitch or "helps companies grow faster",
        sender_name=sender,
    )

    prompt = f"""\
Company: {company_name}{domain_context}
Recipient: {first_name} ({ceo_name})
They're hiring: {job_title_hiring}

Write a cold email from {sender} to {first_name}. Mention the {job_title_hiring} role,
and explain how {settings.company_name or 'we'} can help them get results now instead
of waiting months for the new hire to ramp up.

Respond with exactly:
SUBJECT: <short lowercase subject line>
BODY:
<email text, under 100 words, sign off as {sender}>
"""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
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
        body = raw

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
