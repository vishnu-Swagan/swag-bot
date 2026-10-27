"""MCP approvals never touch stdin or stdout."""

from __future__ import annotations

import io
import sys

import pytest

from swag_bot.errors import SwagError
from swag_bot.interfaces import ActionRequest, RiskLevel
from swag_bot.onboarding.approvals import (
    MCPApprovalPrompter,
    McpApprovals,
    add_grant,
    load_mcp_approvals,
    mcp_approvals_path,
)


def _write(target: str = "hello.txt") -> ActionRequest:
    return ActionRequest(
        kind="write_file",
        summary=f"write {target}",
        risk=RiskLevel.WRITE,
        target=target,
    )


def _destructive() -> ActionRequest:
    return ActionRequest(
        kind="delete",
        summary="delete the tree",
        risk=RiskLevel.DESTRUCTIVE,
        target="tree",
    )


def test_prompt_is_silent_and_does_not_read_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("stdin was read")

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys.stdin, "read", refuse)
    monkeypatch.setattr(sys.stdin, "readline", refuse)
    prompter = MCPApprovalPrompter(reason="unsupported")
    assert prompter.prompt(_write()) is False
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "elicitation" in prompter.explain()
    assert "stdin" in prompter.explain()


def test_task_yes_does_not_cover_destructive_and_a_grant_does() -> None:
    blanket = MCPApprovalPrompter(allow_risky=True, reason="elicited")
    assert blanket.prompt(_write()) is True
    assert blanket.prompt(_destructive()) is False
    assert "destructive" in blanket.explain()

    granted = MCPApprovalPrompter(
        allow_risky=False,
        reason="unsupported",
        grants=McpApprovals(risks=["write", "destructive"]),
    )
    assert granted.prompt(_write()) is True
    assert granted.prompt(_destructive()) is True
    assert granted.explain() == ""


def test_declined_prompt_stops_the_step() -> None:
    prompter = MCPApprovalPrompter(allow_risky=False, reason="declined")
    with pytest.raises(SwagError, match="declined"):
        prompter.prompt(_write())
    assert "declined" in prompter.explain().lower()


def test_grant_command_persists_under_swag_home() -> None:
    stored = add_grant("write")
    assert stored.risks == ["write"]
    assert load_mcp_approvals().risks == ["write"]
    assert mcp_approvals_path().is_file()
    with pytest.raises(ValueError):
        add_grant("   ")
