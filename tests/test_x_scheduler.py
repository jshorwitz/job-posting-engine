from __future__ import annotations

from datetime import datetime

from engine.x.linkedin_scheduler import get_next_post as get_next_linkedin_post
from engine.x.scheduled_post import get_next_post
from engine.x.time_utils import should_enrich_now, should_linkedin_post_now, should_post_now


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class TestXCalendarSelection:
    def test_friday_4pm_pt_keeps_friday_copy(self):
        calendar = {
            "week_1": [
                {"day": "friday", "text": "friday post"},
                {"day": "saturday", "text": "saturday post"},
            ]
        }

        post_id, post = get_next_post(calendar, set(), now=_utc("2026-03-07T00:00:00+00:00"))

        assert post_id == "week_1_0"
        assert post["day"] == "friday"

    def test_linkedin_selector_uses_pacific_day(self):
        calendar = {
            "week_1": [
                {"day": "friday", "text": "friday linkedin"},
                {"day": "saturday", "text": "saturday linkedin"},
            ]
        }

        post_id, post = get_next_linkedin_post(calendar, set(), now=_utc("2026-03-07T00:00:00+00:00"))

        assert post_id == "week_1_0"
        assert post["day"] == "friday"


class TestSchedulerWindows:
    def test_x_post_slots_follow_pacific_time_across_dst(self):
        assert should_post_now(None, _utc("2026-03-06T17:00:00+00:00"))
        assert should_post_now(None, _utc("2026-03-07T00:00:00+00:00"))
        assert should_post_now(None, _utc("2026-03-09T16:00:00+00:00"))
        assert not should_post_now(None, _utc("2026-03-09T17:00:00+00:00"))
        assert not should_post_now("2026-03-09-09", _utc("2026-03-09T16:30:00+00:00"))

    def test_linkedin_post_slot_follows_pacific_time(self):
        assert should_linkedin_post_now(None, _utc("2026-03-10T16:00:00+00:00"))
        assert not should_linkedin_post_now(None, _utc("2026-03-10T17:00:00+00:00"))
        assert not should_linkedin_post_now("2026-03-10", _utc("2026-03-10T16:00:00+00:00"))

    def test_enrichment_slot_follows_eastern_time(self):
        assert should_enrich_now(None, _utc("2026-03-09T13:00:00+00:00"))
        assert not should_enrich_now(None, _utc("2026-03-09T14:00:00+00:00"))
        assert not should_enrich_now("2026-03-09", _utc("2026-03-09T13:00:00+00:00"))
