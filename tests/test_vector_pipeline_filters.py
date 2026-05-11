from dataclasses import dataclass

from engine.vector_filters import should_skip_vector_visitor


@dataclass
class Visitor:
    visitor_email: str
    visitor_name: str


def visitor(email: str, name: str = "Ada Lovelace") -> Visitor:
    return Visitor(
        visitor_email=email,
        visitor_name=name,
    )


def test_skips_personal_email_domains():
    skip, reason = should_skip_vector_visitor(visitor("ada@gmail.com"))

    assert skip is True
    assert "personal email domain" in reason


def test_skips_missing_contact_name():
    skip, reason = should_skip_vector_visitor(visitor("ada@example.com", name=""))

    assert skip is True
    assert reason == "missing contact name"


def test_allows_named_business_email():
    skip, reason = should_skip_vector_visitor(visitor("ada@example.com"))

    assert skip is False
    assert reason == ""
