from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
EASTERN_TZ = ZoneInfo("America/New_York")
X_POST_HOURS_PT = (9, 12, 15, 18)
LINKEDIN_POST_HOUR_PT = 9
LINKEDIN_POST_DAYS = {1, 2, 3, 5}  # Tue, Wed, Thu, Sat
SYNTER_CAMPAIGN_HOUR_PT = 9
SYNTER_CAMPAIGN_DAY = 1  # Tuesday
ENRICHMENT_HOUR_ET = 9
ENRICHMENT_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri
JOB_DISCOVERY_HOUR_ET = 8
JOB_DISCOVERY_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri
LISTICLE_OUTREACH_HOUR_ET = 10
LISTICLE_OUTREACH_DAY = 1  # Tuesday
FOLLOWUP_HOUR_ET = 11
FOLLOWUP_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri


def ensure_timezone(now: datetime | None, tz: ZoneInfo) -> datetime:
    """Normalize a datetime into the requested timezone."""
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        return current.replace(tzinfo=tz)
    return current.astimezone(tz)


def weekday_name(now: datetime | None, tz: ZoneInfo) -> str:
    return ensure_timezone(now, tz).strftime("%A").lower()


def date_str(now: datetime | None, tz: ZoneInfo) -> str:
    return ensure_timezone(now, tz).strftime("%Y-%m-%d")


def slot_key(now: datetime | None, tz: ZoneInfo) -> str:
    return ensure_timezone(now, tz).strftime("%Y-%m-%d-%H")


def should_post_now(last_post_slot: str | None, now: datetime | None = None) -> bool:
    current = ensure_timezone(now, PACIFIC_TZ)
    return current.hour in X_POST_HOURS_PT and slot_key(current, PACIFIC_TZ) != last_post_slot


def should_linkedin_post_now(last_li_date: str | None, now: datetime | None = None) -> bool:
    current = ensure_timezone(now, PACIFIC_TZ)
    return (
        current.hour == LINKEDIN_POST_HOUR_PT
        and current.weekday() in LINKEDIN_POST_DAYS
        and date_str(current, PACIFIC_TZ) != last_li_date
    )


def should_enrich_now(last_enrich_date: str | None, now: datetime | None = None) -> bool:
    current = ensure_timezone(now, EASTERN_TZ)
    return (
        current.hour == ENRICHMENT_HOUR_ET
        and current.weekday() in ENRICHMENT_DAYS
        and date_str(current, EASTERN_TZ) != last_enrich_date
    )


def should_job_discovery_now(last_job_date: str | None, now: datetime | None = None) -> bool:
    """Daily job discovery — Mon-Fri at 8am ET."""
    current = ensure_timezone(now, EASTERN_TZ)
    return (
        current.hour == JOB_DISCOVERY_HOUR_ET
        and current.weekday() in JOB_DISCOVERY_DAYS
        and date_str(current, EASTERN_TZ) != last_job_date
    )


def should_listicle_outreach_now(last_listicle_date: str | None, now: datetime | None = None) -> bool:
    """Weekly listicle/podcast outreach — Tuesdays at 10am ET."""
    current = ensure_timezone(now, EASTERN_TZ)
    return (
        current.hour == LISTICLE_OUTREACH_HOUR_ET
        and current.weekday() == LISTICLE_OUTREACH_DAY
        and date_str(current, EASTERN_TZ) != last_listicle_date
    )


def should_synter_campaign_now(last_campaign_date: str | None, now: datetime | None = None) -> bool:
    """Synter campaign posts — Tuesdays at 9am PT (LinkedIn + X @synterai)."""
    current = ensure_timezone(now, PACIFIC_TZ)
    return (
        current.hour == SYNTER_CAMPAIGN_HOUR_PT
        and current.weekday() == SYNTER_CAMPAIGN_DAY
        and date_str(current, PACIFIC_TZ) != last_campaign_date
    )


def should_followup_now(last_followup_date: str | None, now: datetime | None = None) -> bool:
    """Daily follow-up check — Mon-Fri at 11am ET."""
    current = ensure_timezone(now, EASTERN_TZ)
    return (
        current.hour == FOLLOWUP_HOUR_ET
        and current.weekday() in FOLLOWUP_DAYS
        and date_str(current, EASTERN_TZ) != last_followup_date
    )
