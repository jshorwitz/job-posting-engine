from scripts.emailbison_report import (
    build_report,
    classify_reply,
    normalize_reply,
    summarize_campaign,
)


def test_classify_reply_marks_demo_requests_urgent():
    priority, reason = classify_reply(
        {"body": "Can you send pricing and book a demo?", "status": "not_automated_reply"}
    )

    assert priority == "urgent"
    assert "High-intent" in reason


def test_classify_reply_demotes_unsubscribe():
    priority, reason = classify_reply({"body": "Please unsubscribe me", "status": "negative"})

    assert priority == "low"
    assert "unsubscribe" in reason


def test_normalize_reply_handles_nested_lead():
    reply = normalize_reply(
        {
            "id": 123,
            "campaign_id": 456,
            "lead": {
                "id": 99,
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "company": "Example Co",
            },
            "body": "Interested in a pilot.",
            "created_at": "2026-05-10T12:00:00Z",
            "status": "interested",
        }
    )

    assert reply.lead_name == "Ada Lovelace"
    assert reply.lead_email == "ada@example.com"
    assert reply.priority == "urgent"


def test_summarize_campaign_calculates_reply_rate():
    replies = [
        normalize_reply({"id": 1, "body": "Interested", "status": "interested"}),
        normalize_reply({"id": 2, "body": "Thanks", "status": "not_automated_reply"}),
    ]

    summary = summarize_campaign(
        {
            "id": 42,
            "name": "CMO campaign",
            "stats": {"sent": 100, "opened": 50},
        },
        replies,
    )

    assert summary["sent"] == 100
    assert summary["replies"] == 2
    assert summary["reply_rate"] == 0.02
    assert summary["interested"] == 1


def test_build_report_uses_default_campaign_ids_from_fake_client(monkeypatch):
    class FakeClient:
        def get_campaigns(self):
            return [{"id": 42, "name": "CMO campaign", "stats": {"sent": 100}}]

        def get_campaign(self, campaign_id):
            assert campaign_id == "42"
            return {"id": 42, "name": "CMO campaign", "stats": {"sent": 100}}

        def get_campaign_replies(self, campaign_id, **kwargs):
            return [{"id": 1, "campaign_id": campaign_id, "body": "Book a demo?", "status": "interested"}]

    monkeypatch.setenv("EMAILBISON_CAMPAIGN_ID", "42")
    report = build_report(FakeClient(), [], max_pages=1)

    assert report["read_only"] is True
    assert report["totals"]["campaigns"] == 1
    assert report["totals"]["urgent_replies"] == 1
