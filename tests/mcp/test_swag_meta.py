"""``_meta.swag`` parsing. No MCP SDK required."""

from __future__ import annotations

from swag_bot.mcp.meta import swag_meta


def test_meta_and_underscore_meta() -> None:
    class WithMeta:
        meta = {
            "swag": {
                "risk": "network",
                "trust": "trusted",
                "source": "web",
                "sinks": ["network"],
            }
        }

    parsed = swag_meta(WithMeta())
    assert parsed == {
        "risk": "network",
        "trust": "trusted",
        "source": "web",
        "sinks": ["network"],
    }

    class WithUnderscore:
        _meta = {"swag": {"risk": "destructive"}, "other": {"risk": "read"}}

    assert swag_meta(WithUnderscore()) == {"risk": "destructive"}


def test_dict_and_missing_swag() -> None:
    assert swag_meta({"_meta": {"swag": {"source": "plugin:demo"}}}) == {"source": "plugin:demo"}
    assert swag_meta({"meta": {}}) == {}
    assert swag_meta(object()) == {}
