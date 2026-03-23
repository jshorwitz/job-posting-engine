"""Generate personalized webinar series invite emails for cold outreach.

Uses the same OpenAI-powered approach as email_writer.py but with a
webinar-specific CTA instead of a product pitch.
"""

from __future__ import annotations

import logging

from openai import OpenAI

from engine.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You write cold emails that feel like they were typed on a phone between meetings. Punchy,
curiosity-driven, and impossible to ignore.

ABSOLUTE RULES:
- NO emojis. None.
- NO em dashes. Use periods or commas.
- ONE exclamation mark max in entire email.
- NO words like: leverage, unlock, game-changer, cutting-edge, streamline, elevate,
  supercharge, revolutionize, next-level, synergy, robust, seamless, holistic, innovative.
- NO "I hope this finds you well", "I came across your company", "I'd love to connect".
- NO bullet points or numbered lists. Write like a person, not a pitch deck.
- Under 80 words. 4-6 short lines with line breaks between thoughts.

CONTEXT:
You're inviting marketing leaders to a free 12-week webinar series called
"Growth Machines with AI Agents" hosted by {sender_name} at Synter.

The series covers: audiences, campaigns, landing pages, conversion tracking,
attribution, creative, reporting, email orchestration, and more. All built
live with AI Agents. Every Thursday 10AM PT. Free, replay included.

Series page: syntermedia.ai/lp/growth-machines

STRUCTURE:
1. Open with a specific observation about their hiring situation (they're hiring for a marketing role).
2. Mention that you're running a free series on building growth machines with AI instead of headcount.
3. Name 2-3 topics from the series that are relevant to their role/company.
4. Low-friction CTA: "worth checking out if you're building the team right now"
5. Sign off as {sender_name}, end with "Sent from my iPhone".

Tone: casual, peer-to-peer, like texting a friend who runs marketing.
"""


def generate_webinar_invite(
    settings: Settings,
    contact_name: str,
    company_name: str,
    job_title_hiring: str,
    company_domain: str | None = None,
) -> tuple[str, str]:
    """Generate a personalized webinar series invite email.

    Returns:
        Tuple of (subject_line, email_body).
    """
    client = OpenAI(api_key=settings.openai_api_key)

    first_name = contact_name.split()[0] if contact_name else "there"
    sender = settings.sender_name or "Joel"

    system = SYSTEM_PROMPT.format(sender_name=sender)

    prompt = f"""\
Company: {company_name}
Website: {company_domain or 'unknown'}
Recipient: {first_name} ({contact_name})
They're hiring: {job_title_hiring}

Write a cold email from {sender} inviting {first_name} to the Growth Machines
with AI Agents webinar series. Reference the {job_title_hiring} role they're
hiring for and explain how the series covers exactly what that new hire would do,
but with AI Agents.

Respond with exactly:
SUBJECT: <short lowercase subject line>
BODY:
<email text, under 80 words, sign off as {sender}>
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

    text = response.choices[0].message.content.strip()

    subject = ""
    body = ""
    if "SUBJECT:" in text and "BODY:" in text:
        subject = text.split("SUBJECT:")[1].split("BODY:")[0].strip()
        body = text.split("BODY:")[1].strip()
    else:
        lines = text.split("\n", 1)
        subject = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else text

    # Clean up any residual "SUBJECT:" prefix the AI might have left
    while subject.upper().startswith("SUBJECT:"):
        subject = subject[len("SUBJECT:"):].strip()

    return subject, body
