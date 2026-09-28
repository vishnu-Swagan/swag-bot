"""The MCP approval form title is the action and target."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from mcp.server.mcpserver.resolve import Elicit

from swag_bot.onboarding.approvals import approval_title
from swag_bot.onboarding.mcp_bridge import resolve_task_approval


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        client_capabilities=SimpleNamespace(elicitation=SimpleNamespace(form={}, url=None))
    )


def test_title_is_run_plus_target() -> None:
    goal = (
        "Write fizzbuzz.py that prints the numbers 1 to 15, one per line, "
        "and run it with python3. The last line is FizzBuzz."
    )
    assert approval_title(goal) == "Run: python3 fizzbuzz.py"
    decision = resolve_task_approval(goal, _ctx())  # type: ignore[arg-type]
    assert isinstance(decision, Elicit)
    assert decision.message == "Run: python3 fizzbuzz.py"
    assert len(decision.message) < 40
    assert "tha..." not in decision.message
    schema = decision.schema.model_json_schema()
    assert schema["title"] == "Run: python3 fizzbuzz.py"
    body = schema["properties"]["allow"]["description"]
    assert "Destructive actions stay denied." in body
    assert "fizzbuzz.py" in body
    assert len(decision.message) < len(body)


def test_write_only_title_does_not_include_the_rest_of_the_goal() -> None:
    goal = "Write fizzbuzz.py that prints fizzbuzz for the numbers one through twenty."
    assert approval_title(goal) == "Write: fizzbuzz.py"
    decision = resolve_task_approval(goal, _ctx())  # type: ignore[arg-type]
    assert isinstance(decision, Elicit)
    assert decision.message == "Write: fizzbuzz.py"
