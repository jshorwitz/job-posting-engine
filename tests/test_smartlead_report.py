from scripts.smartlead_report import (
    build_report,
    campaign_metrics,
    classify_reply,
    html_to_text,
    normalize_reply,
)


def test_html_to_text_strips_html():
    assert html_to_text("<div>Hello&nbsp;</div><div>World</div>") == "Hello World"


def test_classify_reply_priorities():
    assert classify_reply("Yes, book a demo")[0] == "urgent"
    assert classify_reply("Stop")[0] == "low"
    assert classify_reply("For business inquiries, please contact John")[0] == "normal"


def test_normalize_reply_uses_latest_reply_message():
    reply = normalize_reply(
        {
            "email_campaign_id": 42,
            "email_campaign_name": "Vector Visitors",
            "lead_first_name": "Ada",
            "lead_last_name": "Lovelace",
            "lead_email": "ada@example.com",
            "last_reply_time": "2026-05-10T12:00:00Z",
            "email_history": [
                {"type": "SENT", "time": "2026-05-10T11:00:00Z", "email_body": "Hi"},
                {
                    "type": "REPLY",
                    "time": "2026-05-10T12:00:00Z",
                    "email_body": "<div>Can we see pricing?</div>",
                    "stats_id": "abc",
                },
            ],
        }
    )

    assert reply.lead_name == "Ada Lovelace"
    assert reply.priority == "urgent"
    assert reply.stats_id == "abc"


def test_campaign_metrics_counts_rows():
    metrics = campaign_metrics(
        {
            "data": [
                {"sent_time": "2026-05-10", "reply_time": "2026-05-11", "is_bounced": False},
                {"sent_time": "2026-05-10", "open_count": 1, "is_bounced": True},
            ]
        }
    )

    assert metrics["sent"] == 2
    assert metrics["replied"] == 1
    assert metrics["bounced"] == 1
    assert metrics["reply_rate"] == 0.5


def test_build_report_with_fake_client():
    class FakeClient:
        def get_campaign_statistics(self, campaign_id):
            return {"data": [{"sent_time": "2026-05-10", "reply_time": "2026-05-11"}]}

        def get_inbox_replies(self, campaign_ids, limit=50):
            return [
                {
                    "email_campaign_id": campaign_ids[0],
                    "email_campaign_name": "Vector Visitors",
                    "lead_first_name": "Ada",
                    "lead_last_name": "Lovelace",
                    "lead_email": "ada@example.com",
                    "last_reply_time": "2026-05-11",
                    "email_history": [{"type": "REPLY", "email_body": "Stop"}],
                }
            ]

    report = build_report(FakeClient(), ["42"])
    assert report["read_only"] is True
    assert report["metrics"]["42"]["replied"] == 1
    assert report["totals"]["low_replies"] == 1
