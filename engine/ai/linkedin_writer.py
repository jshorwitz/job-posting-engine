"""OpenAI-powered LinkedIn message generation.

Connection request notes: max 300 characters.
InMail messages: max ~1900 characters (subject max 200).
"""

from __future__ import annotations

import logging

from openai import OpenAI

from engine.config import Settings

logger = logging.getLogger(__name__)

CONNECTION_NOTE_SYSTEM = """\
You are writing a LinkedIn connection request note (MAX 300 characters).
Be direct, reference their hiring signal, offer value. No fluff.
Tone: peer-to-peer, confident, concise. Sign off with just your first name.
"""

INMAIL_SYSTEM = """\
You are writing a LinkedIn InMail via Sales Navigator.
Write short, personalized messages under 150 words.
Reference the specific hiring signal. Offer a concrete insight about
how you can help. End with one clear CTA.
Tone: confident but not pushy, peer-to-peer, conversational.
Never use "I hope this finds you well" or "I came across your company."
"""


def generate_connection_note(
    settings: Settings,
    ceo_name: str,
    company_name: str,
    job_title_hiring: str,
) -> str:
    """Generate a ≤300 char connection request note."""
    sender = settings.sender_name or "there"
    first_name = ceo_name.split()[0] if ceo_name else "there"

    if not settings.openai_api_key:
        return (
            f"Hi {first_name} — saw {company_name} is hiring a "
            f"{job_title_hiring}. I help scaling companies accelerate "
            f"growth. Would love to connect. – {sender}"
        )[:300]

    client = OpenAI(api_key=settings.openai_api_key)

    prompt = f"""\
Company: {company_name}
CEO/Founder: {ceo_name}
Open role: {job_title_hiring}
Sender: {sender}

Write a LinkedIn connection request note from {sender}. MUST be under 300 characters.
Reference the {job_title_hiring} hire as the reason for reaching out.
"""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": CONNECTION_NOTE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=100,
    )

    note = (response.choices[0].message.content or "").strip()
    if len(note) > 300:
        note = note[:297] + "..."

    logger.info(f"Generated connection note for {ceo_name} ({len(note)} chars)")
    return note


def generate_inmail(
    settings: Settings,
    ceo_name: str,
    company_name: str,
    job_title_hiring: str,
    company_domain: str | None = None,
) -> tuple[str, str]:
    """Generate an InMail subject + body via OpenAI."""
    sender = settings.sender_name or "there"
    first_name = ceo_name.split()[0] if ceo_name else "there"

    if not settings.openai_api_key:
        subject = f"Re: your {job_title_hiring} hire"
        body = (
            f"Hi {first_name},\n\n"
            f"Noticed {company_name} is hiring a {job_title_hiring} — "
            f"great growth signal.\n\n"
            f"I help scaling companies build growth engines "
            f"that complement new hires. Happy to share a few "
            f"strategies that have worked for similar companies.\n\n"
            f"Open to a quick call this week?\n\n{sender}"
        )
        return subject, body

    client = OpenAI(api_key=settings.openai_api_key)
    domain_context = f"\nWebsite: {company_domain}" if company_domain else ""

    prompt = f"""\
Company: {company_name}{domain_context}
CEO/Founder: {ceo_name}
Open role: {job_title_hiring}

Write a LinkedIn InMail from {sender} to {ceo_name}.
The fact that they're hiring a {job_title_hiring} signals growth ambition.
Offer a specific insight about how you can help them scale.

Respond with exactly two sections:
SUBJECT: <subject line, max 200 chars>
BODY:
<message — first-name greeting, 2-3 short paragraphs, CTA, sign off as {sender}>
"""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": INMAIL_SYSTEM},
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

    subject = subject[:200]

    logger.info(f"Generated InMail for {ceo_name} @ {company_name}: {subject}")
    return subject, body


def _parse_subject_body(raw: str) -> tuple[str, str]:
    """Parse SUBJECT: / BODY: from OpenAI response."""
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
