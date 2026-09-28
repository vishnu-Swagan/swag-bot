"""Built-in tools, local fallbacks, redaction, and the task-list labels."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from swag_bot.core.artifacts import default_output_dir, write_run_artifacts
from swag_bot.core.display import display_status, render_table
from swag_bot.core.fallbacks import FallbackMemory, FallbackPolicy, FallbackPrompter, LocalSandbox
from swag_bot.core.redact import redact
from swag_bot.core.tools import register_builtin_tools
from swag_bot.interfaces import (
    TIMEOUT_EXIT_CODE,
    ActionLogEntry,
    ActionRequest,
    AutonomyLevel,
    RiskLevel,
    Step,
    StepStatus,
    TaskPlan,
    ToolCall,
)
from swag_bot.registry import InMemoryToolRegistry
from tests.fakes import FakeSandbox


def test_builtin_tools_use_the_sandbox(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "box")
    registry = InMemoryToolRegistry()
    register_builtin_tools(registry, sandbox)
    wrote = registry.call(
        ToolCall(id="1", name="write_file", arguments={"path": "notes/a.txt", "content": "hi"})
    )
    assert wrote == "wrote notes/a.txt"
    assert (
        registry.call(ToolCall(id="2", name="read_file", arguments={"path": "notes/a.txt"}))
        == "hi\n"
    )
    text = registry.call(
        ToolCall(id="3", name="run_shell", arguments={"command": "echo hi", "timeout": 2})
    )
    assert "exit_code=0" in text
    assert sandbox.commands == ["echo hi"]
    escaped = registry.call(
        ToolCall(id="4", name="write_file", arguments={"path": "../outside.txt", "content": "no"})
    )
    assert escaped.startswith("error:")
    missing = registry.call(ToolCall(id="5", name="read_file", arguments={"path": "nope.txt"}))
    assert missing.startswith("error:")


def test_existing_tool_is_not_replaced(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "box")
    registry = InMemoryToolRegistry()
    from swag_bot.interfaces import Tool

    registry.register(Tool(name="read_file", description="custom"), lambda path: "custom")
    register_builtin_tools(registry, sandbox)
    assert registry.call(ToolCall(id="1", name="read_file", arguments={"path": "a"})) == "custom"


def test_local_sandbox_timeout_and_path_jail(tmp_path: Path) -> None:
    sandbox = LocalSandbox(tmp_path / "box")
    sandbox.write_file("note.txt", "hi")
    assert sandbox.read_file("note.txt") == "hi"
    result = sandbox.run("sleep 5", timeout=0.2)
    assert result.timed_out is True
    assert result.exit_code == TIMEOUT_EXIT_CODE
    from swag_bot.errors import SandboxError

    with pytest.raises(SandboxError):
        sandbox.write_file("../escape.txt", "no")


def test_fallback_memory_and_policy() -> None:
    store = FallbackMemory()
    item = store.add("Alpha note", metadata={"tag": "docs"})
    assert store.search("alpha")[0].id == item.id
    assert store.search("   ") == []
    assert store.delete(item.id) is True
    policy = FallbackPolicy(AutonomyLevel.ASK_RISKY)
    read = ActionRequest(kind="read_file", summary="read", risk=RiskLevel.READ)
    write = ActionRequest(kind="write_file", summary="write", risk=RiskLevel.WRITE)
    assert policy.requires_approval(read) is False
    assert policy.requires_approval(write) is True


def test_fallback_prompter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("swag_bot.core.fallbacks.typer.confirm", lambda *args, **kwargs: False)
    action = ActionRequest(kind="tool", summary="run", risk=RiskLevel.EXECUTE)
    assert FallbackPrompter().prompt(action) is False


def test_display_labels_and_artifacts(tmp_path: Path) -> None:
    assert display_status(StepStatus.DOING) == "running"
    assert display_status(StepStatus.VERIFYING) == "running"
    assert display_status(StepStatus.DONE) == "done"
    assert display_status(StepStatus.FAILED) == "failed"
    plan = TaskPlan(goal="g", steps=[Step(id="a", title="One", status=StepStatus.DONE)])
    table = render_table(plan)
    assert table.title == "Tasks"
    directory = tmp_path / "out"
    entry = ActionLogEntry(
        action=ActionRequest(kind="read_file", summary="read a", risk=RiskLevel.READ),
        autonomy=AutonomyLevel.ASK_RISKY,
        approved=True,
        approver="policy",
        outcome="ok",
    )
    write_run_artifacts(directory, plan, [entry], "# Summary\n\nDone.\n")
    assert (directory / ".swag" / "plan.json").is_file()
    assert not (directory / "plan.json").exists()
    assert (directory / "summary.md").read_text(encoding="utf-8").startswith("# Summary")
    line = (directory / ".swag" / "action-log.jsonl").read_text(encoding="utf-8").strip()
    assert ActionLogEntry.model_validate_json(line).outcome == "ok"
    stamp = default_output_dir()
    assert stamp.parts[0] == "swag-output"
    assert re.fullmatch(r"\d{8}-\d{6}(?:-[0-9a-f]{6})?", stamp.name)


def test_redact_nested_secrets() -> None:
    cleaned = redact({"api_key": "sekret", "note": "token=abc", "ok": "plain"})
    assert cleaned["api_key"] == "[redacted]"
    assert "abc" not in cleaned["note"]
    assert cleaned["ok"] == "plain"
