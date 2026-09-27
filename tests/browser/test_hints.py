"""MCP tool metadata becomes permission hints only for a tagged plugin."""

from __future__ import annotations

from types import SimpleNamespace

from swag_bot.mcp.client import _swag_hints


def test_hints_require_a_plugin_and_a_swag_block() -> None:
    tool = SimpleNamespace(meta={"swag": {"risk": "read", "permission": "mcp"}})
    assert _swag_hints(tool, plugin=None) == (None, None, None)
    assert _swag_hints(tool, plugin="browser") == ("read", "mcp", "browser")
    assert _swag_hints(SimpleNamespace(meta=None), plugin="browser") == (None, None, None)
    assert _swag_hints(SimpleNamespace(meta={"other": 1}), plugin="browser") == (None, None, None)


def test_blank_hints_are_ignored() -> None:
    tool = SimpleNamespace(meta={"swag": {"risk": "  ", "permission": ""}})
    assert _swag_hints(tool, plugin="browser") == (None, None, None)
