"""Drip scheduler — sends the next due email for each active contact.

Called by the pipeline via `--drip` flag. On each run:
  1. Query all DripState records with status=ACTIVE
  2. For each, check if enough days have elapsed since last_sent_at
  3. If due, render the template with enrichment data
  4. Push rendered subject/body to Loops contact properties
  5. Fire `drip_email` event to trigger the send
  6. Advance current_step; mark COMPLETED after step 18

Requires ONE Loop automation in Loops UI:
  - Trigger: `drip_email` event
  - Email step: Subject = {{drip_subject}}, Body = {{drip_body}}
  - From: joel@mail.syntermedia.ai, Reply-to: joel@syntermedia.ai
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from engine.config import Settings
from engine.db.models import DripState, DripStatus
from engine.drip.sequence import DRIP_SEQUENCE, render_template
from engine.drip.sequence_smb import SMB_DRIP_SEQUENCE

CAMPAIGN_SEQUENCES: dict[str, list] = {
    "growth_hire": DRIP_SEQUENCE,
    "smb_local": SMB_DRIP_SEQUENCE,
}

logger = logging.getLogger(__name__)


def enroll_contact(
    session: Session,
    email: str,
    first_name: str,
    company: str,
    enrichment_data: dict,
    campaign: str = "growth_hire",
) -> DripState | None:
    """Enroll a contact in the drip sequence.

    Args:
        campaign: Which sequence to use — "growth_hire" (default, tech/startup)
                  or "smb_local" (real estate, HVAC, and other SMB verticals).

    If already enrolled, returns None (no-op).
    """
    existing = session.query(DripState).filter(DripState.email == email).first()
    if existing:
        logger.debug(f"Drip: {email} already enrolled (step {existing.current_step}, campaign={existing.campaign})")
        return None

    state = DripState(
        email=email,
        first_name=first_name,
        company=company,
        campaign=campaign,
        current_step=0,
        status=DripStatus.ACTIVE,
        enrichment_json=json.dumps(enrichment_data, default=str),
    )
    session.add(state)
    session.flush()
    logger.info(f"Drip: enrolled {email} ({company}) → campaign={campaign}")
    return state


def run_drip(
    session: Session,
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int = 50,
    campaign: str | None = None,
) -> dict[str, int]:
    """Process all active drip contacts and send due emails.

    Args:
        campaign: If set, only process contacts in this campaign
                  ("growth_hire" or "smb_local"). If None, processes all.

    Returns stats dict with sent/skipped/completed/failed counts.
    """
    from engine.outreach.loops_sender import send_drip_email

    stats = {"checked": 0, "sent": 0, "skipped": 0, "completed": 0, "failed": 0}
    now = datetime.now(timezone.utc)

    query = session.query(DripState).filter(DripState.status == DripStatus.ACTIVE)
    if campaign:
        query = query.filter(DripState.campaign == campaign)
    active = query.limit(limit).all()

    logger.info(f"Drip: {len(active)} active contacts to check")

    for state in active:
        stats["checked"] += 1
        next_step_idx = state.current_step  # 0-indexed into sequence

        # Select the correct sequence based on the contact's campaign
        sequence = CAMPAIGN_SEQUENCES.get(state.campaign or "growth_hire", DRIP_SEQUENCE)

        if next_step_idx >= len(sequence):
            # All 18 emails sent
            state.status = DripStatus.COMPLETED
            state.completed_at = now
            stats["completed"] += 1
            continue

        step = sequence[next_step_idx]
        delay_days = step["delay_days"]

        # Check if enough time has elapsed
        # SQLite stores naive datetimes — normalize to UTC-aware for comparison
        def _aware(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        if state.last_sent_at:
            elapsed = (now - _aware(state.last_sent_at)).total_seconds() / 86400
            if elapsed < delay_days:
                stats["skipped"] += 1
                continue
        elif delay_days > 0:
            elapsed = (now - _aware(state.enrolled_at)).total_seconds() / 86400
            if elapsed < delay_days:
                stats["skipped"] += 1
                continue

        # Load enrichment data and build template context
        try:
            enrichment = json.loads(state.enrichment_json)
        except (json.JSONDecodeError, TypeError):
            enrichment = {}

        # Add built-in fields to template context
        enrichment["firstName"] = state.first_name or enrichment.get("firstName", "")
        enrichment["company"] = state.company or enrichment.get("company", "")

        # Render subject and body
        subject = render_template(step["subject"], enrichment)
        body = render_template(step["body"], enrichment)

        if dry_run:
            logger.info(
                f"[DRY RUN] Drip step {step['step']}/18 → {state.email}\n"
                f"  Subject: {subject}\n"
                f"  Body: {body[:120]}..."
            )
            state.current_step = next_step_idx + 1
            state.last_sent_at = now
            stats["sent"] += 1
            if state.current_step >= len(sequence):
                state.status = DripStatus.COMPLETED
                state.completed_at = now
                stats["completed"] += 1
            continue

        # Send via Loops
        ok = send_drip_email(
            settings=settings,
            email=state.email,
            subject=subject,
            body=body,
        )

        if ok:
            state.current_step = next_step_idx + 1
            state.last_sent_at = now
            stats["sent"] += 1
            logger.info(
                f"Drip: sent step {step['step']}/18 → {state.email} | {subject}"
            )

            # Check if sequence is complete
            if state.current_step >= len(sequence):
                state.status = DripStatus.COMPLETED
                state.completed_at = now
                stats["completed"] += 1
        else:
            stats["failed"] += 1
            logger.error(f"Drip: failed step {step['step']} → {state.email}")

    session.commit()

    logger.info(
        f"Drip run complete: {stats['sent']} sent, {stats['skipped']} not due, "
        f"{stats['completed']} completed, {stats['failed']} failed"
    )
    return stats
