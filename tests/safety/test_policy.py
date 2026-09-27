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
from swag_bot.safety.policy import (
    DefaultPermissionPolicy,
    PolicyDecision,
    change_grant,
    load_grants,
    load_suspended_grants,
    save_grants,
    write_grant_maps,
)


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


def test_save_grants_keeps_suspended_plugins(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    write_grant_maps({"files": ["filesystem.read"]}, {"quiet": ["network"]}, path)
    save_grants({"files": ["filesystem.read", "shell"]}, path)
    assert load_grants(path)["files"] == {"filesystem.read", "shell"}
    assert load_suspended_grants(path)["quiet"] == {"network"}
    assert "quiet" not in load_grants(path)


def test_change_grant_on_a_suspended_plugin_stays_suspended(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    write_grant_maps({}, {"quiet": ["network"]}, path)
    change_grant("quiet", "mcp", add=True, path=path)
    assert "quiet" not in load_grants(path)
    assert load_suspended_grants(path)["quiet"] == {"mcp", "network"}


def test_tool_risk_hint_is_not_forced_up_to_execute() -> None:
    policy = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY)
    read = _action(
        "tool",
        summary="browser__snapshot",
        risk=RiskLevel.READ,
        risk_hint="read",
        plugin="browser",
        permission="mcp",
    )
    network = _action(
        "tool",
        summary="browser__navigate https://example.com",
        risk=RiskLevel.NETWORK,
        risk_hint="network",
        plugin="browser",
        permission="network",
    )
    untagged = _action("tool", summary="Call MCP tool demo__echo", risk=RiskLevel.READ)
    write = _action(
        "tool",
        summary="browser__fill #q",
        risk=RiskLevel.WRITE,
        risk_hint="write",
    )
    assert policy.classify(read) is RiskLevel.READ
    assert policy.requires_approval(read) is False
    assert policy.classify(write) is RiskLevel.WRITE
    assert policy.classify(network) is RiskLevel.NETWORK
    assert policy.requires_approval(network) is True
    assert policy.classify(untagged) is RiskLevel.EXECUTE


def test_read_hint_still_rises_when_the_summary_deletes() -> None:
    policy = DefaultPermissionPolicy(AutonomyLevel.AUTO)
    action = _action(
        "tool",
        summary="browser__snapshot delete the file",
        risk=RiskLevel.READ,
        risk_hint="read",
    )
    assert policy.classify(action) is RiskLevel.DESTRUCTIVE


def test_ask_always_still_prompts_a_granted_read() -> None:
    policy = DefaultPermissionPolicy(
        AutonomyLevel.ASK_ALWAYS,
        grants={"files": ["filesystem.read"]},
    )
    action = _action(ActionKind.READ_FILE.value, summary="read", plugin="files")
    assert policy.decide(action) is PolicyDecision.PROMPT
