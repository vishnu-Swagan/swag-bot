"""Permission decisions for each autonomy level."""

from __future__ import annotations

from pathlib import Path

import pytest

from swag_bot.interfaces import (
    ActionKind,
    ActionRequest,
    AutonomyLevel,
    RiskLevel,
    default_requires_approval,
)
from swag_bot.safety.policy import DefaultPermissionPolicy, PolicyDecision


def _action(
    kind: str,
    *,
    risk: RiskLevel = RiskLevel.READ,
    summary: str = "do the thing",
    target: str | None = None,
    **arguments: object,
) -> ActionRequest:
    return ActionRequest(
        kind=kind,
        summary=summary,
        risk=risk,
        target=target,
        arguments=dict(arguments),
    )


@pytest.mark.parametrize(
    ("kind", "summary", "expected"),
    [
        (ActionKind.READ_FILE.value, "read notes", RiskLevel.READ),
        (ActionKind.WRITE_FILE.value, "write notes", RiskLevel.WRITE),
        (ActionKind.RUN_COMMAND.value, "run a command", RiskLevel.EXECUTE),
        ("shell", "shell command", RiskLevel.EXECUTE),
        (ActionKind.NETWORK.value, "fetch a page", RiskLevel.NETWORK),
        ("send_message", "send a message to the team", RiskLevel.NETWORK),
        ("spend", "spend money on the invoice", RiskLevel.DESTRUCTIVE),
        (ActionKind.DELETE.value, "delete the file", RiskLevel.DESTRUCTIVE),
        ("tool", "Call MCP tool demo__delete_file", RiskLevel.DESTRUCTIVE),
    ],
)
def test_classify_risky_actions(kind: str, summary: str, expected: RiskLevel) -> None:
    policy = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY)
    action = _action(kind, summary=summary, risk=RiskLevel.READ)
    assert policy.classify(action) is expected


def test_write_outside_workdir_is_destructive(tmp_path: Path) -> None:
    policy = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY, workdir=tmp_path)
    outside = _action(ActionKind.WRITE_FILE.value, summary="write", target="../secret")
    inside = _action(
        ActionKind.WRITE_FILE.value,
        summary="write",
        target="notes.txt",
        risk=RiskLevel.WRITE,
    )
    assert policy.classify(outside) is RiskLevel.DESTRUCTIVE
    assert policy.classify(inside) is RiskLevel.WRITE
    absolute = _action(ActionKind.WRITE_FILE.value, summary="write", target=str(tmp_path / "x"))
    assert policy.classify(absolute) is RiskLevel.DESTRUCTIVE


def test_classify_does_not_lower_destructive() -> None:
    policy = DefaultPermissionPolicy(AutonomyLevel.AUTO)
    action = _action(ActionKind.READ_FILE.value, summary="read", risk=RiskLevel.DESTRUCTIVE)
    assert policy.classify(action) is RiskLevel.DESTRUCTIVE


def test_unknown_permission_is_risky() -> None:
    policy = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY)
    action = _action(
        "com.example.deploy",
        summary="deploy",
        permission="com.example.deploy",
    )
    assert policy.classify(action) is not RiskLevel.READ
    assert policy.requires_approval(action) is True


@pytest.mark.parametrize("autonomy", list(AutonomyLevel))
@pytest.mark.parametrize("risk", list(RiskLevel))
def test_never_prompts_less_often_than_the_default(
    autonomy: AutonomyLevel, risk: RiskLevel
) -> None:
    policy = DefaultPermissionPolicy(autonomy)
    action = _action("custom", summary="custom", risk=risk)
    if default_requires_approval(autonomy, risk):
        assert policy.requires_approval(action) is True


def test_decisions_per_autonomy_level() -> None:
    read = _action(ActionKind.READ_FILE.value, summary="read notes")
    shell = _action(ActionKind.RUN_COMMAND.value, summary="run tests")
    always = DefaultPermissionPolicy(AutonomyLevel.ASK_ALWAYS)
    risky = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY)
    auto = DefaultPermissionPolicy(AutonomyLevel.AUTO)

    assert always.decide(read) is PolicyDecision.PROMPT
    assert always.decide(shell) is PolicyDecision.PROMPT
    assert risky.decide(read) is PolicyDecision.ALLOW
    assert risky.decide(shell) is PolicyDecision.PROMPT
    assert auto.decide(read) is PolicyDecision.ALLOW
    assert auto.decide(shell) is PolicyDecision.ALLOW
    assert auto.requires_approval(shell) is False


def test_plugin_grants_hard_deny() -> None:
    policy = DefaultPermissionPolicy(
        AutonomyLevel.AUTO,
        grants={"files": ["filesystem.read"]},
    )
    allowed = _action(ActionKind.READ_FILE.value, summary="read", plugin="files")
    denied = _action(ActionKind.WRITE_FILE.value, summary="write", target="a.txt", plugin="files")
    assert policy.is_denied(allowed) is False
    assert policy.decide(allowed) is PolicyDecision.ALLOW
    assert policy.is_denied(denied) is True
    assert policy.decide(denied) is PolicyDecision.DENY
    assert policy.requires_approval(denied) is False

    policy.grant("files", ["filesystem.write"])
    assert policy.decide(denied) is PolicyDecision.ALLOW
    policy.revoke("files", "filesystem.write")
    assert policy.decide(denied) is PolicyDecision.DENY


def test_ask_always_still_prompts_a_granted_read() -> None:
    policy = DefaultPermissionPolicy(
        AutonomyLevel.ASK_ALWAYS,
        grants={"files": ["filesystem.read"]},
    )
    action = _action(ActionKind.READ_FILE.value, summary="read", plugin="files")
    assert policy.decide(action) is PolicyDecision.PROMPT
