"""Undo ledger: shell edits and deletes, step restore, and irreversible prompts."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.config import Settings
from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.interfaces import (
    ActionKind,
    ActionRequest,
    AutonomyLevel,
    ChatResponse,
    Message,
    PluginManifest,
    Reversibility,
    RiskLevel,
    StepStatus,
    Tool,
    ToolCall,
    default_requires_approval,
)
from swag_bot.mcp.registry import compensation_annotation
from swag_bot.safety.compensation import CompensationCall, CompensationRegistry, CompensationSpec
from swag_bot.safety.policy import DefaultPermissionPolicy, PolicyDecision
from swag_bot.safety.prompter import RichApprovalPrompter
from swag_bot.safety.reversibility import classify_reversibility, command_is_irreversible
from swag_bot.safety.sandbox import LocalSandbox
from swag_bot.safety.undo import UndoLedger, UndoSandbox
from tests.cli_output import visible
from tests.core.support import StaticPolicy, plan_json
from tests.fakes import AutoApprovePrompter, FakeLLMClient, InMemoryMemoryStore

runner = CliRunner()

_SHELL = (
    r"printf '%s\n' after > edit.txt"
    r" && rm -f keep.txt"
    r" && rm -f dir/inner.txt"
    r" && rm -f link.txt"
    r" && mkdir -p extra empty"
    r" && printf '%s\n' new > extra/created.txt"
    r" && printf '%s\n' x > bin.dat"
)


def _workspace(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / "dir").mkdir(parents=True)
    (work / "keep.txt").write_text("keep-me\n", encoding="utf-8")
    (work / "edit.txt").write_text("before\n", encoding="utf-8")
    (work / "dir" / "inner.txt").write_text("inner\n", encoding="utf-8")
    (work / "bin.dat").write_bytes(b"\x00\x01\xff")
    (work / "link.txt").symlink_to("keep.txt")
    return work


def _assert_original(work: Path) -> None:
    assert (work / "keep.txt").read_text(encoding="utf-8") == "keep-me\n"
    assert (work / "edit.txt").read_text(encoding="utf-8") == "before\n"
    assert (work / "dir" / "inner.txt").read_text(encoding="utf-8") == "inner\n"
    assert (work / "bin.dat").read_bytes() == b"\x00\x01\xff"
    assert (work / "link.txt").is_symlink()
    assert (work / "link.txt").readlink() == Path("keep.txt")
    assert not (work / "extra").exists()
    assert not (work / "empty").exists()


def test_shell_edits_and_deletes_are_fully_undone(tmp_path: Path) -> None:
    work = _workspace(tmp_path)
    ledger = UndoLedger.open(work)
    sandbox = UndoSandbox(LocalSandbox(work), ledger)
    ledger.begin_run("run-shell", work)
    ledger.begin_step("trash")
    result = sandbox.run(_SHELL)
    assert result.exit_code == 0
    assert not (work / "keep.txt").exists()
    assert (work / "edit.txt").read_text(encoding="utf-8") == "after\n"
    assert (work / "extra" / "created.txt").read_text(encoding="utf-8") == "new\n"
    assert (work / "empty").is_dir()
    assert (work / "bin.dat").read_bytes() == b"x\n"
    reasons = [item.reason for item in ledger.checkpoints]
    assert "before-shell" in reasons

    report = ledger.rollback_run()
    _assert_original(work)
    assert report.restored_to == "run-start"
    assert report.files_changed > 0
    assert report.irreversible == []

    again = ledger.rollback_run()
    _assert_original(work)
    assert again.files_changed == 0


def test_undo_to_a_step_keeps_earlier_shell_edits(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    ledger = UndoLedger.open(work)
    sandbox = UndoSandbox(LocalSandbox(work), ledger)
    ledger.begin_run("run-steps", work)
    ledger.begin_step("one")
    first = sandbox.run(r"printf '%s\n' from-step-one > a.txt")
    assert first.exit_code == 0
    ledger.begin_step("two")
    second = sandbox.run(r"printf '%s\n' from-step-two > b.txt && rm -f a.txt")
    assert second.exit_code == 0
    assert not (work / "a.txt").exists()
    assert (work / "b.txt").is_file()

    report = ledger.rollback_run(to_step="two")
    assert report.restored_to == "two"
    assert (work / "a.txt").read_text(encoding="utf-8") == "from-step-one\n"
    assert not (work / "b.txt").exists()

    full = ledger.rollback_run()
    assert not (work / "a.txt").exists()
    assert full.restored_to == "run-start"


def test_cli_undo_and_undo_to_step(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("safe\n", encoding="utf-8")
    ledger = UndoLedger.open(work)
    sandbox = UndoSandbox(LocalSandbox(work), ledger)
    ledger.begin_run("cli-run", work)
    ledger.begin_step("one")
    sandbox.run(r"printf '%s\n' one > one.txt")
    ledger.begin_step("two")
    sandbox.run(r"rm -f keep.txt && printf '%s\n' two > two.txt")
    assert not (work / "keep.txt").exists()

    stepped = runner.invoke(app, ["undo", "--run", "cli-run", "--to", "two"])
    assert stepped.exit_code == 0, visible(stepped)
    text = visible(stepped)
    assert "two" in text
    assert (work / "keep.txt").read_text(encoding="utf-8") == "safe\n"
    assert (work / "one.txt").read_text(encoding="utf-8") == "one\n"
    assert not (work / "two.txt").exists()

    # The step restore already put keep.txt back. Delete it again, then undo the run.
    (work / "keep.txt").unlink()
    (work / "later.txt").write_text("later\n", encoding="utf-8")
    # The ledger's base snapshot still has the original tree. A new shell
    # command after undo is a further mutation and is itself snapshotted.
    sandbox.run(r"printf '%s\n' nope > keep.txt")
    whole = runner.invoke(app, ["undo", "--run", "cli-run"])
    assert whole.exit_code == 0, visible(whole)
    assert "start of the run" in visible(whole)
    assert (work / "keep.txt").read_text(encoding="utf-8") == "safe\n"
    assert not (work / "one.txt").exists()
    assert not (work / "later.txt").exists()


def test_cli_undo_without_history() -> None:
    result = runner.invoke(app, ["undo"])
    assert result.exit_code == 1
    assert "no undo history" in visible(result)


def test_undo_help_shows_to() -> None:
    result = runner.invoke(app, ["undo", "--help"])
    assert result.exit_code == 0
    text = visible(result)
    assert "--to" in text
    assert "--run" in text


def test_run_that_shells_out_can_be_undone(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("safe\n", encoding="utf-8")
    (work / "edit.txt").write_text("old\n", encoding="utf-8")
    command = r"printf '%s\n' new > edit.txt && rm -f keep.txt && printf '%s\n' x > created.txt"
    ledger = UndoLedger.open(work)
    loop = PlanDoVerifyLoop(
        llm=FakeLLMClient(
            [
                plan_json(
                    [
                        {
                            "id": "trash",
                            "title": "Edit and delete files",
                            "instruction": "use the shell",
                            "success_criteria": "the files changed",
                        }
                    ]
                ),
                ChatResponse(
                    message=Message.assistant(
                        tool_calls=[
                            ToolCall(id="t1", name="run_shell", arguments={"command": command})
                        ]
                    )
                ),
                ChatResponse(message=Message.assistant("edited and deleted")),
                json.dumps({"passed": True, "reason": "ok", "replan": False}),
                "summary",
            ]
        ),
        sandbox=UndoSandbox(LocalSandbox(work), ledger),
        memory=InMemoryMemoryStore(),
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        undo=ledger,
        concurrency=1,
    )
    plan = loop.run("edit and delete files with the shell")
    assert plan.steps[0].status is StepStatus.DONE
    assert not (work / "keep.txt").exists()
    assert (work / "edit.txt").read_text(encoding="utf-8") == "new\n"
    assert (work / "created.txt").read_text(encoding="utf-8") == "x\n"
    assert any(item.reason == "before-shell" for item in ledger.checkpoints)

    ledger.rollback_run()
    assert (work / "keep.txt").read_text(encoding="utf-8") == "safe\n"
    assert (work / "edit.txt").read_text(encoding="utf-8") == "old\n"
    assert not (work / "created.txt").exists()


def test_failed_step_rolls_the_workspace_back(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("safe\n", encoding="utf-8")
    command = r"rm -f keep.txt && printf '%s\n' x > created.txt"
    ledger = UndoLedger.open(work, auto_rollback=True)
    loop = PlanDoVerifyLoop(
        llm=FakeLLMClient(
            [
                plan_json(
                    [
                        {
                            "id": "trash",
                            "title": "Delete a file",
                            "instruction": "use the shell",
                            "success_criteria": "done",
                        }
                    ]
                ),
                ChatResponse(
                    message=Message.assistant(
                        tool_calls=[
                            ToolCall(id="t1", name="run_shell", arguments={"command": command})
                        ]
                    )
                ),
                ChatResponse(message=Message.assistant("deleted it")),
                json.dumps({"passed": False, "reason": "the file is gone", "replan": False}),
                "summary",
            ]
        ),
        sandbox=UndoSandbox(LocalSandbox(work), ledger),
        memory=InMemoryMemoryStore(),
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        undo=ledger,
        max_attempts=1,
        concurrency=1,
    )
    plan = loop.run("delete keep.txt")
    assert plan.steps[0].status is StepStatus.FAILED
    assert (work / "keep.txt").read_text(encoding="utf-8") == "safe\n"
    assert not (work / "created.txt").exists()


def test_network_shell_is_irreversible_but_workdir_files_still_restore(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "edit.txt").write_text("before\n", encoding="utf-8")
    command = r"printf '%s\n' changed > edit.txt; curl --max-time 1 http://127.0.0.1:1 || true"
    action = ActionRequest(
        kind=ActionKind.RUN_COMMAND.value,
        summary="curl and edit",
        risk=RiskLevel.NETWORK,
        target=command,
        tool_name="run_shell",
    )
    assert command_is_irreversible(command) is True
    assert classify_reversibility(action) is Reversibility.IRREVERSIBLE

    ledger = UndoLedger.open(work)
    sandbox = UndoSandbox(LocalSandbox(work), ledger)
    ledger.begin_run("mixed", work)
    ledger.begin_step("mix")
    sandbox.run(command)
    ledger.note_action(action)
    assert (work / "edit.txt").read_text(encoding="utf-8") == "changed\n"

    report = ledger.rollback_run()
    assert (work / "edit.txt").read_text(encoding="utf-8") == "before\n"
    assert any("curl" in item for item in report.irreversible)


def test_compensations_run_in_reverse(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    calls: list[str] = []

    def _close(call: CompensationCall) -> str:
        calls.append(f"{call.inverse}:{call.resolved.get('number')}")
        return "closed"

    registry = CompensationRegistry()
    registry.register(
        CompensationSpec(
            tool="create_issue",
            inverse="close_issue",
            argument_map={"number": "number"},
        ),
        _close,
    )
    ledger = UndoLedger.open(work, compensations=registry)
    sandbox = UndoSandbox(LocalSandbox(work), ledger)
    ledger.begin_run("saga", work)
    ledger.begin_step("book")
    ledger.note_action(
        ActionRequest(
            kind=ActionKind.TOOL.value,
            summary="create issue 1",
            risk=RiskLevel.NETWORK,
            tool_name="create_issue",
            arguments={"number": 1},
        )
    )
    ledger.note_action(
        ActionRequest(
            kind=ActionKind.TOOL.value,
            summary="create issue 2",
            risk=RiskLevel.NETWORK,
            tool_name="create_issue",
            arguments={"number": 2},
        )
    )
    sandbox.run("rm -f a.txt")
    report = ledger.rollback_run()
    assert (work / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert calls == ["close_issue:2", "close_issue:1"]
    assert report.compensations_ran == ["close_issue: closed", "close_issue: closed"]


def test_missing_compensation_handler_is_reported(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    registry = CompensationRegistry()
    registry.register(
        CompensationSpec(
            tool="create_event",
            inverse="delete_event",
            entrypoint="swag_bot_missing_compensation:delete_event",
        )
    )
    ledger = UndoLedger.open(work, compensations=registry)
    ledger.begin_run("ext", work)
    ledger.begin_step("book")
    ledger.note_action(
        ActionRequest(
            kind="tool",
            summary="create a calendar event",
            risk=RiskLevel.NETWORK,
            tool_name="create_event",
        )
    )
    report = ledger.rollback_run()
    assert report.compensations_ran == []
    assert report.compensations_skipped
    assert "create a calendar event" in report.compensations_skipped[0]


def test_ask_irreversible_prompts_only_at_the_point_of_no_return(tmp_path: Path) -> None:
    policy = DefaultPermissionPolicy(AutonomyLevel.ASK_IRREVERSIBLE, workdir=tmp_path)
    write = ActionRequest(
        kind=ActionKind.WRITE_FILE.value,
        summary="write notes.txt",
        risk=RiskLevel.WRITE,
        target="notes.txt",
        tool_name="write_file",
    )
    shell = ActionRequest(
        kind=ActionKind.RUN_COMMAND.value,
        summary="rm notes.txt",
        risk=RiskLevel.DESTRUCTIVE,
        target="rm -f notes.txt",
        tool_name="run_shell",
    )
    curl = ActionRequest(
        kind=ActionKind.RUN_COMMAND.value,
        summary="curl https://example.invalid",
        risk=RiskLevel.NETWORK,
        target="curl https://example.invalid",
        tool_name="run_shell",
    )
    mail = ActionRequest(
        kind="email",
        summary="send an email to ada",
        risk=RiskLevel.NETWORK,
        tool_name="send_email",
    )
    outside = ActionRequest(
        kind=ActionKind.WRITE_FILE.value,
        summary="write outside",
        risk=RiskLevel.WRITE,
        target="../secret",
        tool_name="write_file",
    )
    assert policy.reversibility(write) is Reversibility.REVERSIBLE
    assert policy.requires_approval(write) is False
    assert policy.decide(write) is PolicyDecision.ALLOW
    assert policy.reversibility(shell) is Reversibility.REVERSIBLE
    assert policy.requires_approval(shell) is False
    assert policy.reversibility(curl) is Reversibility.IRREVERSIBLE
    assert policy.requires_approval(curl) is True
    assert policy.decide(curl) is PolicyDecision.PROMPT
    assert policy.requires_approval(mail) is True
    assert policy.reversibility(outside) is Reversibility.IRREVERSIBLE

    risky = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY, workdir=tmp_path)
    assert risky.requires_approval(write) is True
    assert risky.requires_approval(shell) is True
    assert default_requires_approval(AutonomyLevel.ASK_RISKY, RiskLevel.WRITE) is True
    assert default_requires_approval(AutonomyLevel.ASK_IRREVERSIBLE, RiskLevel.DESTRUCTIVE) is False
    assert (
        default_requires_approval(
            AutonomyLevel.ASK_IRREVERSIBLE,
            RiskLevel.NETWORK,
            reversibility=Reversibility.IRREVERSIBLE,
        )
        is True
    )
    assert Settings().autonomy is AutonomyLevel.ASK_RISKY
    assert Settings().undo.enabled is True


def test_irreversible_action_is_flagged_in_the_prompt() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, no_color=True, width=100)
    seen: dict[str, str] = {}

    def confirm(prompt: str, *, default: bool = False) -> bool:
        seen["prompt"] = prompt
        assert default is False
        return False

    prompter = RichApprovalPrompter(console=console, confirm=confirm)
    action = ActionRequest(
        kind=ActionKind.RUN_COMMAND.value,
        summary="curl https://example.invalid",
        risk=RiskLevel.NETWORK,
        target="curl https://example.invalid",
        tool_name="run_shell",
    )
    assert prompter.prompt(action) is False
    text = buffer.getvalue()
    assert "irreversible" in text
    assert "point of no return" in text
    assert "point of no return" in seen["prompt"]


def test_plugin_and_mcp_compensation_declarations() -> None:
    manifest = PluginManifest.from_plugin_json(
        {
            "name": "issues",
            "compensations": [
                {
                    "tool": "create_issue",
                    "inverse": "close_issue",
                    "argument_map": {"number": "number"},
                }
            ],
        }
    )
    registry = CompensationRegistry()
    registry.load_entries(manifest.compensations, source="issues")
    spec = registry.lookup("create_issue")
    assert spec is not None
    assert spec.inverse == "close_issue"

    tool = Tool(
        name="github__create_issue",
        annotations={
            "swagCompensation": {
                "inverse": "github__close_issue",
                "description": "Close the created issue.",
            }
        },
    )
    raw = compensation_annotation(tool)
    assert raw is not None
    assert raw["inverse"] == "github__close_issue"
    assert compensation_annotation(Tool(name="plain")) is None


def test_shell_heuristic_flags_escape_and_allows_in_workdir_rm() -> None:
    assert command_is_irreversible("rm -f notes.txt") is False
    assert command_is_irreversible("rm -rf /tmp/gone") is True
    assert command_is_irreversible("echo hi > /tmp/out") is True
    assert command_is_irreversible("git push origin main") is True
    assert command_is_irreversible("printf '%s\n' hi > notes.txt") is False
    paid = ActionRequest(
        kind="spend",
        summary="spend money on the invoice",
        risk=RiskLevel.DESTRUCTIVE,
    )
    assert classify_reversibility(paid) is Reversibility.IRREVERSIBLE
