"""``swag safety`` commands."""

from __future__ import annotations

from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.interfaces import ActionKind, ActionLogEntry, ActionRequest, AutonomyLevel, RiskLevel
from swag_bot.safety.log import ActionLog
from tests.cli_output import visible

runner = CliRunner()


def test_policy_prints_autonomy_and_rules() -> None:
    result = runner.invoke(app, ["safety", "policy"])
    assert result.exit_code == 0
    text = visible(result)
    assert "ask-risky" in text
    assert "destructive" in text.lower()
    assert "plugin grants" in text


def test_grant_shows_up_in_policy_and_log_is_empty() -> None:
    granted = runner.invoke(app, ["safety", "grant", "files", "filesystem.read"])
    assert granted.exit_code == 0
    policy = runner.invoke(app, ["safety", "policy"])
    shown = visible(policy)
    assert "files" in shown
    assert "filesystem.read" in shown
    revoked = runner.invoke(app, ["safety", "revoke", "files", "filesystem.read"])
    assert revoked.exit_code == 0
    empty = runner.invoke(app, ["safety", "log"])
    assert empty.exit_code == 0
    assert "No actions logged" in visible(empty)


def test_log_prints_entries() -> None:
    ActionLog().append(
        ActionLogEntry(
            action=ActionRequest(
                kind=ActionKind.READ_FILE.value,
                summary="read notes",
                risk=RiskLevel.READ,
            ),
            autonomy=AutonomyLevel.ASK_RISKY,
            approved=True,
            approver="policy",
        )
    )
    result = runner.invoke(app, ["safety", "log"])
    assert result.exit_code == 0
    text = visible(result)
    assert "read notes" in text
    assert "policy" in text
