"""Append-only action log and authorize()."""

from __future__ import annotations

from pathlib import Path

from swag_bot.interfaces import (
    ActionKind,
    ActionLogEntry,
    ActionRequest,
    AutonomyLevel,
    RiskLevel,
)
from swag_bot.safety.log import ActionLog, authorize
from swag_bot.safety.policy import DefaultPermissionPolicy
from swag_bot.safety.redact import REDACTED


class _Answer:
    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.seen: list[ActionRequest] = []

    def prompt(self, action: ActionRequest) -> bool:
        self.seen.append(action)
        return self.allow


def _entry(summary: str, *, approved: bool = True) -> ActionLogEntry:
    return ActionLogEntry(
        action=ActionRequest(
            kind=ActionKind.WRITE_FILE.value,
            summary=summary,
            risk=RiskLevel.WRITE,
            arguments={"api_key": "sk-testsecretvalue1234567890"},
        ),
        autonomy=AutonomyLevel.ASK_RISKY,
        approved=approved,
        approver="user",
    )


def test_log_is_append_only_and_redacts(tmp_path: Path) -> None:
    path = tmp_path / "actions.jsonl"
    log = ActionLog(path)
    first = log.append(_entry("write notes"))
    second = log.append(_entry("write more", approved=False))
    text = path.read_text(encoding="utf-8")
    assert "sk-testsecretvalue1234567890" not in text
    assert REDACTED in text
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 2
    again = ActionLog(path).read()
    assert [item.id for item in again] == [first.id, second.id]
    assert again[0].action.arguments["api_key"] == REDACTED
    assert again[1].approved is False
    reread = path.read_text(encoding="utf-8").splitlines()[0]
    assert reread == lines[0]


def test_authorize_prompts_logs_and_hides_secrets(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    policy = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY)
    prompter = _Answer(True)
    action = ActionRequest(
        kind=ActionKind.RUN_COMMAND.value,
        summary="run with password=hunter2",
        risk=RiskLevel.EXECUTE,
        arguments={"token": "abcdef1234567890"},
    )
    assert authorize(action, policy=policy, prompter=prompter, log=log) is True
    assert prompter.seen
    assert "hunter2" not in prompter.seen[0].summary
    assert prompter.seen[0].arguments["token"] == REDACTED
    stored = log.read()
    assert stored[0].approver == "user"
    assert stored[0].approved is True
    assert "hunter2" not in log.path.read_text(encoding="utf-8")
    assert "abcdef1234567890" not in log.path.read_text(encoding="utf-8")


def test_authorize_hard_deny_does_not_prompt(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    policy = DefaultPermissionPolicy(AutonomyLevel.ASK_ALWAYS, grants={"files": []})
    prompter = _Answer(True)
    action = ActionRequest(
        kind=ActionKind.READ_FILE.value,
        summary="read",
        risk=RiskLevel.READ,
        arguments={"plugin": "files"},
    )
    assert authorize(action, policy=policy, prompter=prompter, log=log) is False
    assert prompter.seen == []
    assert log.read()[0].approver == "policy"


def test_auto_approver_label(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    policy = DefaultPermissionPolicy(AutonomyLevel.AUTO)
    action = ActionRequest(
        kind=ActionKind.DELETE.value,
        summary="delete the cache",
        risk=RiskLevel.DESTRUCTIVE,
    )
    assert authorize(action, policy=policy, prompter=_Answer(False), log=log) is True
    entry = log.read()[0]
    assert entry.approver == "auto"
    assert entry.action.risk is RiskLevel.DESTRUCTIVE
