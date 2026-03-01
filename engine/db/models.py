"""SQLAlchemy ORM models for deduplication and state tracking."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EmailStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


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
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EmailLog(Base):
    """Tracks every email attempt for deduplication and reporting."""

    __tablename__ = "email_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_domain: Mapped[str] = mapped_column(String(255), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str] = mapped_column(String(255))
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
