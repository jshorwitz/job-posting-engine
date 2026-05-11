from engine.ai.vector_visitor_email import (
    first_name,
    render_vector_visitor_email,
    render_vector_visitor_sequence,
)


def test_first_name_defaults_to_there():
    assert first_name("") == "there"
    assert first_name(None) == "there"
    assert first_name("Ada Lovelace") == "Ada"


def test_initial_vector_email_uses_soft_signal_and_low_friction_cta():
    subject, body = render_vector_visitor_email("Ada Lovelace")

    assert subject == "quick question on paid media"
    assert "Saw someone from your team looking at Synter." in body
    assert "Noticed you were on the site" not in body
    assert "Reply \"Yes\"" not in body
    assert "Worth sending over a 2-minute overview?" in body


def test_follow_ups_do_not_pitch_a_meeting_or_free_trial():
    sequence = render_vector_visitor_sequence("Ada Lovelace")
    combined = "\n".join(
        [
            sequence.follow_up.subject,
            sequence.follow_up.body,
            sequence.final.subject,
            sequence.final.body,
        ]
    )

    assert "book a meeting" not in combined.lower()
    assert "free trial" not in combined.lower()
    assert "short walkthrough" in sequence.follow_up.body
    assert "2-minute walkthrough" in sequence.final.body
