"""Tests for the drip scheduler and sequence rendering."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.db.models import Base, DripState, DripStatus
from engine.drip.scheduler import enroll_contact, run_drip
from engine.drip.sequence import DRIP_SEQUENCE, render_template


# ── Template rendering ───────────────────────────────────────────


class TestRenderTemplate:
    def test_simple_replacement(self):
        result = render_template("Hello {{name}}", {"name": "Joel"})
        assert result == "Hello Joel"

    def test_fallback_when_missing(self):
        result = render_template("Hello {{name|friend}}", {})
        assert result == "Hello friend"

    def test_fallback_when_empty(self):
        result = render_template("Hello {{name|friend}}", {"name": ""})
        assert result == "Hello friend"

    def test_no_fallback_when_present(self):
        result = render_template("Hello {{name|friend}}", {"name": "Joel"})
        assert result == "Hello Joel"

    def test_multiple_vars(self):
        result = render_template(
            "{{firstName}} at {{company}} hiring {{jobTitleHiring}}",
            {"firstName": "Jane", "company": "Acme", "jobTitleHiring": "VP Growth"},
        )
        assert result == "Jane at Acme hiring VP Growth"

    def test_money_values_passthrough(self):
        result = render_template(
            "Spending {{spyfu_monthly_spend}} per month",
            {"spyfu_monthly_spend": "$15,000"},
        )
        assert result == "Spending $15,000 per month"

    def test_no_double_brace_conflict(self):
        """Ensure plain text with single braces is untouched."""
        result = render_template("cost is {not a var}", {})
        assert result == "cost is {not a var}"


# ── Sequence data ────────────────────────────────────────────────


class TestDripSequence:
    def test_has_18_emails(self):
        assert len(DRIP_SEQUENCE) == 18

    def test_steps_are_sequential(self):
        for i, email in enumerate(DRIP_SEQUENCE):
            assert email["step"] == i + 1

    def test_first_email_immediate(self):
        assert DRIP_SEQUENCE[0]["delay_days"] == 0

    def test_all_have_required_fields(self):
        for email in DRIP_SEQUENCE:
            assert "step" in email
            assert "delay_days" in email
            assert "subject" in email
            assert "body" in email
            assert isinstance(email["delay_days"], int)
            assert email["delay_days"] >= 0

    def test_total_days_is_52(self):
        total = sum(e["delay_days"] for e in DRIP_SEQUENCE)
        assert total == 52

    def test_all_bodies_render_without_error(self):
        """All templates should render cleanly with empty data."""
        for email in DRIP_SEQUENCE:
            subject = render_template(email["subject"], {})
            body = render_template(email["body"], {})
            assert isinstance(subject, str)
            assert isinstance(body, str)
            assert len(body) > 20  # sanity check


# ── Enrollment ───────────────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()


class TestEnrollContact:
    def test_enroll_new_contact(self, db_session: Session):
        state = enroll_contact(
            session=db_session,
            email="jane@acme.com",
            first_name="Jane",
            company="Acme Corp",
            enrichment_data={"spyfu_monthly_spend": "$15,000"},
        )
        db_session.commit()
        assert state is not None
        assert state.email == "jane@acme.com"
        assert state.current_step == 0
        assert state.status == DripStatus.ACTIVE

    def test_no_duplicate_enrollment(self, db_session: Session):
        enroll_contact(db_session, "jane@acme.com", "Jane", "Acme", {})
        db_session.commit()
        second = enroll_contact(db_session, "jane@acme.com", "Jane", "Acme", {})
        assert second is None

    def test_enrichment_stored_as_json(self, db_session: Session):
        data = {"spyfu_monthly_spend": "$15,000", "builtwith_installed_pixels": "Google, Meta"}
        state = enroll_contact(db_session, "jane@acme.com", "Jane", "Acme", data)
        db_session.commit()
        loaded = json.loads(state.enrichment_json)
        assert loaded["spyfu_monthly_spend"] == "$15,000"


# ── Scheduler ────────────────────────────────────────────────────


class TestRunDrip:
    def _enroll(self, session, email="jane@acme.com", **kwargs):
        data = {
            "spyfu_monthly_spend": "$15,000",
            "builtwith_installed_pixels": "Google, Meta",
            "builtwith_missing_pixels": "LinkedIn, Reddit",
            "jobTitleHiring": "Head of Growth",
        }
        data.update(kwargs)
        state = enroll_contact(session, email, "Jane", "Acme Corp", data)
        session.commit()
        return state

    def test_first_email_sent_immediately(self, db_session: Session):
        self._enroll(db_session)

        stats = run_drip(db_session, settings=None, dry_run=True)

        assert stats["sent"] == 1
        state = db_session.query(DripState).first()
        assert state.current_step == 1

    def test_second_email_not_due(self, db_session: Session):
        """Email 2 requires 3 days — shouldn't send on same day."""
        state = self._enroll(db_session)
        # Simulate email 1 already sent
        state.current_step = 1
        state.last_sent_at = datetime.now(timezone.utc)
        db_session.commit()

        stats = run_drip(db_session, settings=None, dry_run=True)
        assert stats["skipped"] == 1
        assert stats["sent"] == 0

    def test_second_email_due_after_delay(self, db_session: Session):
        """Email 2 should send after 3 days."""
        state = self._enroll(db_session)
        state.current_step = 1
        state.last_sent_at = datetime.now(timezone.utc) - timedelta(days=4)
        db_session.commit()

        stats = run_drip(db_session, settings=None, dry_run=True)
        assert stats["sent"] == 1
        state = db_session.query(DripState).first()
        assert state.current_step == 2

    def test_sequence_completes_after_18(self, db_session: Session):
        """After step 18, status should be COMPLETED."""
        state = self._enroll(db_session)
        state.current_step = 17  # 0-indexed, so 17 = about to send email 18
        state.last_sent_at = datetime.now(timezone.utc) - timedelta(days=5)
        db_session.commit()

        stats = run_drip(db_session, settings=None, dry_run=True)
        assert stats["sent"] == 1
        assert stats["completed"] == 1
        state = db_session.query(DripState).first()
        assert state.status == DripStatus.COMPLETED

    def test_completed_contacts_skipped(self, db_session: Session):
        state = self._enroll(db_session)
        state.status = DripStatus.COMPLETED
        db_session.commit()

        stats = run_drip(db_session, settings=None, dry_run=True)
        assert stats["checked"] == 0

    def test_paused_contacts_skipped(self, db_session: Session):
        state = self._enroll(db_session)
        state.status = DripStatus.PAUSED
        db_session.commit()

        stats = run_drip(db_session, settings=None, dry_run=True)
        assert stats["checked"] == 0
