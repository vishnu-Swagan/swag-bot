"""Secret redaction."""

from __future__ import annotations

from swag_bot.safety.redact import REDACTED, redact_text, redact_value


def test_redacts_keys_assignments_and_bearer_tokens() -> None:
    text = (
        "use sk-testsecretvalue1234567890 and "
        "password=hunter2 then Bearer abcdefghijklmnop "
        "and AKIAIOSFODNN7EXAMPLE"
    )
    redacted = redact_text(text)
    assert "sk-testsecretvalue1234567890" not in redacted
    assert "hunter2" not in redacted
    assert "abcdefghijklmnop" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert REDACTED in redacted
    assert "use " in redacted


def test_redacts_secret_keys_in_nested_values() -> None:
    cleaned = redact_value(
        {
            "api_key": "sk-testsecretvalue1234567890",
            "note": "token=abcdef123456",
            "nested": ["password: swordfish"],
            "count": 2,
        }
    )
    assert cleaned["api_key"] == REDACTED
    assert "abcdef123456" not in cleaned["note"]
    assert "swordfish" not in cleaned["nested"][0]
    assert cleaned["count"] == 2


def test_plain_text_is_unchanged() -> None:
    assert redact_text("read notes/a.txt") == "read notes/a.txt"
