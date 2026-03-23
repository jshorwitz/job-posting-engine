"""Signal-based lead discovery pipeline.

Orchestrates all signal sources (fundraising, job changes, tech changes)
and feeds discovered leads into the outreach engine via Smartlead.

Usage:
    python -m engine.signals.pipeline                    # Run all signals
    python -m engine.signals.pipeline --signal funding   # Run one signal
    python -m engine.signals.pipeline --dry-run          # Preview only
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

import httpx

from engine.config import Settings
from engine.clients.hunter import HunterClient
from engine.enrichment import enrich_lead
from engine.ai.email_writer import generate_outreach_email
from engine.outreach.smartlead_sender import send_email as smartlead_send

logger = logging.getLogger(__name__)

# Campaign routing by signal type
GEO_CAMPAIGN_IDS = {
    "americas": os.environ.get("SMARTLEAD_CAMPAIGN_ID_AMERICAS", "3070911"),
    "eu": os.environ.get("SMARTLEAD_CAMPAIGN_ID_EU", "3070909"),
    "apac": os.environ.get("SMARTLEAD_CAMPAIGN_ID_APAC", "3070910"),
}

# Country → geo mapping
COUNTRY_TO_GEO = {
    "United States": "americas", "US": "americas", "Canada": "americas", "CA": "americas",
    "Mexico": "americas", "Brazil": "americas", "Argentina": "americas", "Colombia": "americas",
    "United Kingdom": "eu", "GB": "eu", "Germany": "eu", "DE": "eu",
    "Netherlands": "eu", "NL": "eu", "France": "eu", "FR": "eu",
    "Ireland": "eu", "IE": "eu", "Spain": "eu", "Italy": "eu",
    "Sweden": "eu", "Denmark": "eu", "Norway": "eu", "Finland": "eu",
    "Switzerland": "eu", "Austria": "eu", "Poland": "eu", "Israel": "eu",
    "Belgium": "eu", "Portugal": "eu", "Greece": "eu", "Czechia": "eu",
    "Australia": "apac", "AU": "apac", "New Zealand": "apac", "NZ": "apac",
    "Singapore": "apac", "SG": "apac", "Japan": "apac", "JP": "apac",
    "South Korea": "apac", "KR": "apac", "India": "apac", "IN": "apac",
    "Hong Kong": "apac", "HK": "apac",
    "United Arab Emirates": "eu", "AE": "eu",  # Close enough to EU timezone
    "Saudi Arabia": "eu", "South Africa": "eu",
}


def _get_campaign_id(location: str) -> str:
    """Route to correct geo campaign based on location."""
    geo = COUNTRY_TO_GEO.get(location, "americas")  # Default to Americas
    return GEO_CAMPAIGN_IDS.get(geo, GEO_CAMPAIGN_IDS["americas"])


def _find_decision_maker_hunter(settings: Settings, domain: str) -> dict | None:
    """Use Hunter.io domain search to find a marketing decision maker."""
    if not settings.hunter_api_key:
        return None

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                "https://api.hunter.io/v2/domain-search",
                params={
                    "domain": domain,
                    "api_key": settings.hunter_api_key,
                    "limit": 10,
                    "department": "marketing",
                    "seniority": "senior,executive,director",
                },
            )
            if resp.status_code != 200:
                return None

            data = resp.json().get("data", {})
            emails = data.get("emails", [])

            # Priority: marketing titles first
            marketing_titles = ["marketing", "growth", "cmo", "media", "demand", "paid", "digital"]
            for e in emails:
                title_lower = (e.get("position", "") or "").lower()
                if any(t in title_lower for t in marketing_titles):
                    return {
                        "email": e.get("value", ""),
                        "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                        "title": e.get("position", ""),
                    }

            # Fallback: first senior person
            if emails:
                e = emails[0]
                return {
                    "email": e.get("value", ""),
                    "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                    "title": e.get("position", ""),
                }

    except Exception:
        pass
    return None


def _signal_to_personalization(signal: dict) -> str:
    """Convert signal data into a personalization context string for OpenAI."""
    signal_type = signal.get("signal_type", "")

    if signal_type == "fundraising":
        amount = signal.get("funding_amount", "")
        round_name = signal.get("funding_round", "")
        return (
            f"The company recently raised {amount} in {round_name} funding. "
            f"They are likely deploying capital into growth channels and scaling "
            f"their paid media operations. Reference the funding as a congratulations "
            f"and position Synter as a way to scale ad campaigns faster with AI agents."
        )
    elif signal_type == "job_change":
        previous = signal.get("previous_company", "")
        title = signal.get("title", "")
        context = f"This person just started a new role as {title}."
        if previous:
            context += f" They previously worked at {previous}."
        context += (
            " New leaders in their first 90 days want quick wins. "
            "Position Synter as a way to make an immediate impact on paid media "
            "without waiting months to build a team."
        )
        return context
    elif signal_type == "tech_change":
        tech = signal.get("technology_added", "")
        return (
            f"The company recently installed {tech} on their website, "
            f"indicating they are starting or expanding their paid advertising. "
            f"Position Synter as a way to operate campaigns across multiple platforms "
            f"from day one without needing a large team."
        )
    elif signal_type == "multi_platform_advertiser":
        platforms = signal.get("ad_platforms", [])
        return (
            f"The company runs ads on {', '.join(platforms)} ({len(platforms)} platforms). "
            f"They are dealing with dashboard switching and fragmented reporting. "
            f"Position Synter as one interface for all platforms with AI agents handling execution."
        )

    return ""


def run_signal_pipeline(
    settings: Settings,
    *,
    signal_types: list[str] | None = None,
    dry_run: bool = False,
    max_per_signal: int = 30,
) -> dict[str, int]:
    """Run all signal discovery sources and send outreach.

    Args:
        signal_types: Which signals to run. None = all.
                     Options: "funding", "job_changes", "tech_changes"
        dry_run: If True, discover and enrich but don't send.
        max_per_signal: Max leads per signal source.

    Returns stats dict.
    """
    stats = {"discovered": 0, "enriched": 0, "sent": 0, "skipped": 0, "failed": 0}
    all_signals: list[dict[str, Any]] = []
    run_all = signal_types is None

    # --- Fundraising signals ---
    if run_all or "funding" in signal_types:
        logger.info("=" * 50)
        logger.info("[Signals] Running FUNDRAISING discovery...")
        from engine.signals.fundraising import discover_funded_companies
        funded = discover_funded_companies(settings, max_results=max_per_signal)
        all_signals.extend(funded)
        logger.info(f"[Signals] Fundraising: {len(funded)} companies found")

    # --- Job change signals ---
    if run_all or "job_changes" in signal_types:
        logger.info("=" * 50)
        logger.info("[Signals] Running JOB CHANGES discovery...")
        from engine.signals.job_changes import discover_job_changes
        changes = discover_job_changes(settings, max_results=max_per_signal)
        all_signals.extend(changes)
        logger.info(f"[Signals] Job changes: {len(changes)} leaders found")

    # --- Tech stack change signals ---
    if run_all or "tech_changes" in signal_types:
        logger.info("=" * 50)
        logger.info("[Signals] Running TECH CHANGES discovery...")
        from engine.signals.tech_changes import discover_new_advertisers
        new_advertisers = discover_new_advertisers(settings, max_results=max_per_signal)
        all_signals.extend(new_advertisers)
        logger.info(f"[Signals] Tech changes: {len(new_advertisers)} new advertisers found")

    stats["discovered"] = len(all_signals)
    logger.info(f"\n[Signals] Total discovered: {len(all_signals)}")

    if not all_signals:
        return stats

    # --- Enrich and send ---
    hunter = None
    try:
        hunter = HunterClient(settings)
    except ValueError:
        logger.warning("[Signals] Hunter not configured, email finding limited")

    for signal in all_signals:
        email = signal.get("email", "")
        name = signal.get("full_name", "") or f"{signal.get('first_name', '')} {signal.get('last_name', '')}".strip()
        company = signal.get("company_name", "")
        domain = signal.get("company_domain", "") or signal.get("domain", "")
        title = signal.get("title", "")
        location = signal.get("company_location", "") or signal.get("location", "")

        # If no email, try Hunter — first by name, then domain search for decision maker
        if not email and hunter and domain:
            if name:
                result = hunter.find_email(domain, name)
                if result and result.get("email"):
                    email = result["email"]
                    logger.info(f"[Signals] Hunter found: {email} for {name} @ {domain}")

            # If still no email, do a domain search to find a marketing leader
            if not email:
                try:
                    dm = _find_decision_maker_hunter(settings, domain)
                    if dm:
                        email = dm["email"]
                        name = dm.get("name", name)
                        title = dm.get("title", title)
                        logger.info(f"[Signals] Hunter domain search found: {email} ({name}, {title}) @ {domain}")
                except Exception as exc:
                    logger.warning(f"[Signals] Hunter domain search failed for {domain}: {exc}")

        if not email:
            logger.info(f"[Signals] No email for {name} @ {company}, skipping")
            stats["skipped"] += 1
            continue

        # Generate personalized context from signal
        signal_context = _signal_to_personalization(signal)

        # Generate email via OpenAI
        try:
            email_data = generate_outreach_email(
                settings=settings,
                contact_name=name,
                company_name=company,
                company_domain=domain,
                job_title_hiring=title,
                enrichment_data={"signal_context": signal_context},
            )
        except Exception as exc:
            logger.warning(f"[Signals] Email generation failed for {name}: {exc}")
            stats["failed"] += 1
            continue

        stats["enriched"] += 1
        subject = email_data.get("subject", f"quick note for {company}")
        body = email_data.get("body", "")

        if dry_run:
            logger.info(
                f"[DRY RUN] {signal.get('signal_type')} → {email} | {name} @ {company}\n"
                f"  Subject: {subject}\n"
                f"  Body: {body[:200]}..."
            )
            continue

        # Route to correct geo campaign
        campaign_id = _get_campaign_id(location)

        # Send via Smartlead
        success = smartlead_send(
            settings=settings,
            to_email=email,
            to_name=name,
            subject=subject,
            body=body,
            company_name=company,
            job_title=title,
            campaign_id_override=campaign_id,
        )

        if success:
            stats["sent"] += 1
        else:
            stats["failed"] += 1

    logger.info(f"\n{'=' * 50}")
    logger.info(
        f"[Signals] COMPLETE: discovered={stats['discovered']} "
        f"enriched={stats['enriched']} sent={stats['sent']} "
        f"skipped={stats['skipped']} failed={stats['failed']}"
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description="Signal-based lead discovery")
    parser.add_argument("--signal", choices=["funding", "job_changes", "tech_changes"],
                        help="Run specific signal (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=30, help="Max leads per signal")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    settings = Settings()
    signal_types = [args.signal] if args.signal else None

    run_signal_pipeline(
        settings,
        signal_types=signal_types,
        dry_run=args.dry_run,
        max_per_signal=args.limit,
    )


if __name__ == "__main__":
    main()
