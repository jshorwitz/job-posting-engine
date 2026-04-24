"""SQLAlchemy ORM models for deduplication and state tracking."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EmailStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class FollowUpStatus(str, enum.Enum):
    PENDING = "pending"       # eligible but not yet sent
    ENRICHED = "enriched"     # SpyFu data fetched
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"       # no SpyFu data or ineligible
    NO_SPEND = "no_spend"     # SpyFu returned no data for domain


class OutreachType(str, enum.Enum):
    EMAIL = "email"
    LINKEDIN_INMAIL = "linkedin_inmail"
    LINKEDIN_CONNECTION = "linkedin_connection"


class LinkedInOutreachStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    DAILY_LIMIT = "daily_limit"


class JobPosting(Base):
    """A growth leadership job posting discovered via Sumble."""

    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sumble_job_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    company_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_title: Mapped[str] = mapped_column(String(255))
    job_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    posted_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Contact(Base):
    """A CEO/founder found via Sumble People API."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sumble_person_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    company_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EmailLog(Base):
    """Tracks every email attempt for deduplication and reporting."""

    __tablename__ = "email_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_domain: Mapped[str] = mapped_column(String(255), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    job_title_hiring: Mapped[str] = mapped_column(String(255))
    email_subject: Mapped[str] = mapped_column(String(500))
    email_body_preview: Mapped[str] = mapped_column(Text)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus), default=EmailStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LinkedInOutreach(Base):
    """Tracks LinkedIn connection requests and InMails."""

    __tablename__ = "linkedin_outreach"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_domain: Mapped[str] = mapped_column(String(255), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str] = mapped_column(String(255))
    contact_linkedin: Mapped[str] = mapped_column(String(500), index=True)
    job_title_hiring: Mapped[str] = mapped_column(String(255))
    outreach_type: Mapped[OutreachType] = mapped_column(Enum(OutreachType))
    message_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message_body: Mapped[str] = mapped_column(Text)
    status: Mapped[LinkedInOutreachStatus] = mapped_column(
        Enum(LinkedInOutreachStatus), default=LinkedInOutreachStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RunLog(Base):
    """Tracks each pipeline execution for monitoring and debugging."""

    __tablename__ = "run_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    channel: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    query: Mapped[str] = mapped_column(String(255))
    dry_run: Mapped[str] = mapped_column(String(5), default="false")
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    emails_sent: Mapped[int] = mapped_column(Integer, default=0)
    emails_skipped: Mapped[int] = mapped_column(Integer, default=0)
    linkedin_sent: Mapped[int] = mapped_column(Integer, default=0)
    linkedin_skipped: Mapped[int] = mapped_column(Integer, default=0)
    total_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, default=0)
    followups_sent: Mapped[int] = mapped_column(Integer, default=0)
    followups_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class FollowUpLog(Base):
    """Tracks follow-up emails enriched with SpyFu PPC/SEO data."""

    __tablename__ = "followup_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_log_id: Mapped[int] = mapped_column(Integer, index=True)
    company_domain: Mapped[str] = mapped_column(String(255), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str] = mapped_column(String(255))
    contact_email: Mapped[str] = mapped_column(String(255))

    # SpyFu enrichment
    estimated_monthly_spend: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_annual_spend: Mapped[float | None] = mapped_column(Float, nullable=True)
    ppc_keywords: Mapped[int | None] = mapped_column(Integer, nullable=True)
    organic_keywords: Mapped[int | None] = mapped_column(Integer, nullable=True)
    domain_strength: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_competitor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_ads: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Follow-up email
    email_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_body_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus), default=FollowUpStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DripStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    UNSUBSCRIBED = "unsubscribed"


class DripState(Base):
    """Tracks each contact's position in the 18-email drip sequence."""

    __tablename__ = "drip_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), default="")
    company: Mapped[str] = mapped_column(String(255), default="")

    # Campaign identifies which drip sequence to use:
    #   "growth_hire" — tech/startup companies hiring growth/performance roles (default)
    #   "smb_local"   — SMB/local businesses (real estate, HVAC, etc.) hiring first marketer
    campaign: Mapped[str] = mapped_column(String(50), default="growth_hire")

    # Position in the 18-step sequence (0 = not started, 1 = email 1 sent, etc.)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DripStatus] = mapped_column(
        Enum(DripStatus), default=DripStatus.ACTIVE
    )

    # Enrichment data stored as JSON string for template rendering
    enrichment_json: Mapped[str] = mapped_column(Text, default="{}")

    # Timing
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlatformScan(Base):
    """Tracks ad platform pixel detection per domain from BuiltWith scans.

    One row per (domain, platform) pair. Use to aggregate which platforms
    leads are running and which are missing — helps prioritize platform
    build-out.
    """

    __tablename__ = "platform_scans"
    __table_args__ = (UniqueConstraint("company_domain", "platform", name="uq_domain_platform"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_domain: Mapped[str] = mapped_column(String(255), index=True)
    platform: Mapped[str] = mapped_column(String(50), index=True)
    detected: Mapped[bool] = mapped_column(Boolean, default=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VectorVisitor(Base):
    """Website visitors identified by Vector.co for LinkedIn outreach."""

    __tablename__ = "vector_visitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    visitor_email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    visitor_name: Mapped[str] = mapped_column(String(255), default="")
    company_name: Mapped[str] = mapped_column(String(255), default="")
    company_domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    job_title: Mapped[str] = mapped_column(String(255), default="")
    seniority: Mapped[str] = mapped_column(String(100), default="")
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_page_url: Mapped[str] = mapped_column(String(1000), default="")
    visit_count: Mapped[int] = mapped_column(Integer, default=1)
    icp_match: Mapped[bool] = mapped_column(Boolean, default=False)
    outreach_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    enrichment_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(50), default="vector_webhook")
    first_visited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_visited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ListicleStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    CONTACT_FOUND = "contact_found"
    OUTREACH_SENT = "outreach_sent"
    FOLLOW_UP_1 = "follow_up_1"
    FOLLOW_UP_2 = "follow_up_2"
    LISTED = "listed"
    REJECTED = "rejected"
    NO_RESPONSE = "no_response"


class ListicleTarget(Base):
    """A listicle article to target for Synter placement."""

    __tablename__ = "listicle_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    domain: Mapped[str] = mapped_column(String(255), index=True)
    search_query: Mapped[str] = mapped_column(String(255))
    target_type: Mapped[str] = mapped_column(String(20), default="listicle", index=True)  # "listicle" or "podcast"

    # Metrics (from Ahrefs or similar)
    domain_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    domain_traffic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    article_traffic: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Editor/author contact
    editor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    editor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    editor_linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Outreach tracking
    status: Mapped[ListicleStatus] = mapped_column(
        Enum(ListicleStatus), default=ListicleStatus.DISCOVERED
    )
    synter_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outreach_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    research_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    researched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    research_error: Mapped[str | None] = mapped_column(Text, nullable=True)
