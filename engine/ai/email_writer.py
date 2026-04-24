"""OpenAI-powered personalized outreach email generation."""

from __future__ import annotations

import logging

from openai import OpenAI

from engine.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You write cold emails that feel like they were typed on a phone between meetings. Punchy,
curiosity-driven, and impossible to ignore.

STYLE (study this example closely):
---
Tomorrow in your meeting with Wendy you could walk in with *wait for it*

a list of 10+ accounts that GitHub or GitLab are actively chasing right now

Wouldn't that new $500k+ pipeline make Wendy's jaw drop?

It'll take 10 mins to run this. Interested?

Regards,
{sender_name}

Sent from my iPhone
---

ABSOLUTE RULES:
- NO emojis. None.
- NO em dashes. Use periods or commas.
- ONE exclamation mark max in entire email.
- NO words like: leverage, unlock, game-changer, cutting-edge, streamline, elevate,
  supercharge, revolutionize, next-level, synergy, robust, seamless, holistic, innovative.
- NO "I hope this finds you well", "I came across your company", "I'd love to connect".
- NO bullet points or numbered lists. Write like a person, not a pitch deck.
- Under 80 words. 4-6 short lines with line breaks between thoughts.

STRUCTURE:
1. Open with a specific, vivid scenario about THEIR situation (the job they're hiring for).
2. Drop a curiosity hook or pattern interrupt (use *italics* or a line break for dramatic pause).
3. Paint the concrete result they'd get from {company_name} (use specific numbers when possible).
4. Low-friction CTA. Make it feel effortless, not salesy.
5. Sign off as {sender_name}, always end with "Sent from my iPhone".

WHAT TO SAY:
- Reference the specific role they're hiring for as the hook.
- {company_name} {company_pitch}. They don't have to wait months for a new hire to ramp up.
- Make the value tangible: faster results, campaigns running in days not months, etc.

Tone: casual, peer-to-peer, like texting a friend who runs a company. Lowercase subject line.
"""


def generate_outreach_email(
    settings: Settings,
    ceo_name: str,
    company_name: str,
    job_title_hiring: str,
    company_domain: str | None = None,
    sender_context: str | None = None,
) -> tuple[str, str]:
    """Generate a personalized cold email via OpenAI.

    Args:
        sender_context: Optional local/personal hook to weave in naturally
                        (e.g. "Joel is a UW alum and part of the Pioneer Square Labs ecosystem").

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

    context_line = (
        f"\nSender context (weave in naturally, don't force it): {sender_context}"
        if sender_context else ""
    )

    prompt = f"""\
Company: {company_name}{domain_context}
Recipient: {first_name} ({ceo_name})
They're hiring: {job_title_hiring}{context_line}

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
            # Strip leaked "subject:" lines from the body
            if line.strip().lower().startswith("subject:"):
                continue
            body_lines.append(line)

    return subject, "\n".join(body_lines).strip()
