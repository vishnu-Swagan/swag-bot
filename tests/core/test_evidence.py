"""Evidence ledger: a step passes only when the harness can cite real results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.core.checks import CheckRunner, derive_checks, parse_check_list
from swag_bot.core.display import display_status
from swag_bot.core.evidence import EvidenceLedger, parse_shell_outcome, sha256_text
from swag_bot.core.fallbacks import LocalSandbox
from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.core.prompts import VERIFIER_PREFIX
from swag_bot.interfaces import (
    EVIDENCE_CONTRACT_SPEC,
    EVIDENCE_CONTRACT_VERSION,
    AutonomyLevel,
    ChatResponse,
    Check,
    CommandResult,
    Message,
    RunRecord,
    StepStatus,
    ToolCall,
)
from swag_bot.safety.log import ActionLog
from tests.cli_output import visible
from tests.core.support import StaticPolicy, make_loop, plan_json, verdict
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore

runner = CliRunner()


def _step(
    step_id: str,
    title: str,
    *,
    criteria: str = "the step is done",
    checks: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": step_id,
        "title": title,
        "instruction": title,
        "success_criteria": criteria,
    }
    if checks is not None:
        payload["checks"] = checks
    return payload


def _systems(llm: FakeLLMClient, prefix: str) -> list[list[Message]]:
    return [messages for messages in llm.messages if (messages[0].content or "").startswith(prefix)]


def test_shell_outcome_parser_keeps_stdout_and_stderr() -> None:
    parsed = parse_shell_outcome("exit_code=1 timed_out=false\nstdout:\nFAIL\nstderr:\n1 failed")
    assert parsed == (1, False, "FAIL", "1 failed")
    empty = parse_shell_outcome("exit_code=0 timed_out=false\nstdout:\n\nstderr:\n")
    assert empty == (0, False, "", "")
    assert parse_shell_outcome("not a shell result") is None


def test_derive_checks_from_shorthand_and_plain_language() -> None:
    text = "\n".join(
        [
            "file_exists: report.md",
            'file_contains: summary.md "Total"',
            "cmd: pytest -q exits 0",
            "notes.txt exists",
            'hello.txt contains "hi"',
        ]
    )
    checks = derive_checks(text)
    kinds = [
        (item.kind, item.path, item.command, item.contains, item.expected_exit) for item in checks
    ]
    assert ("file_exists", "report.md", None, None, None) in kinds
    assert ("file_contains", "summary.md", None, "Total", None) in kinds
    assert ("command", None, "pytest -q", None, 0) in kinds
    assert ("file_exists", "notes.txt", None, None, None) in kinds
    assert ("file_contains", "hello.txt", None, "hi", None) in kinds
    explicit = parse_check_list(
        [{"kind": "exit_code", "expected_exit": "0", "schema": {"type": "object"}}]
    )
    assert explicit[0].kind == "exit_code"
    assert explicit[0].expected_exit == 0


def test_wrong_exit_code_fails_even_when_the_model_says_it_passed(tmp_path: Path) -> None:
    """The demo bug: a model claims success while the command exited 1."""
    loop, llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("tests", "Run the tests")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(id="c1", name="run_shell", arguments={"command": "pytest -q"})
                    ]
                )
            ),
            "All tests passed.",
            verdict(True, "the suite is green"),
            "Claimed success.",
        ],
        max_attempts=1,
    )
    sandbox.script(
        CommandResult(command="pytest -q", exit_code=1, stdout="FAIL", stderr="1 failed")
    )
    plan = loop.run("run the tests")
    assert plan.steps[0].status is StepStatus.FAILED
    result = loop.results["tests"]
    assert result.verified is False
    assert result.evidence_ids
    assert "exit_code=1" in (result.error or "")
    assert "All tests passed." in result.observation
    prompts = _systems(llm, VERIFIER_PREFIX)
    assert len(prompts) == 1
    shown = prompts[0][-1].content or ""
    assert "All tests passed." in shown
    assert "exit_code=1" in shown
    assert "id=" in shown
    evidence = loop.ledger.for_step("tests")
    tool = next(item for item in evidence if item.tool == "run_shell")
    assert tool.ok is False
    assert tool.exit_code == 1
    assert tool.stderr == "1 failed"
    assert tool.stdout_sha256 == sha256_text("FAIL")
    assert tool.id in result.evidence_ids


def test_missing_file_fails_when_the_script_never_ran(tmp_path: Path) -> None:
    loop, llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json(
                [
                    _step(
                        "report",
                        "Write the report",
                        checks=[{"id": "report", "kind": "file_exists", "path": "report.md"}],
                    )
                ]
            ),
            "I wrote report.md. The template is done.",
            "The report was not written.",
        ],
        max_attempts=1,
    )
    plan = loop.run("write the report")
    assert plan.steps[0].status is StepStatus.FAILED
    assert not (sandbox.workdir / "report.md").exists()
    error = loop.results["report"].error or ""
    assert "report.md does not exist" in error
    assert loop.results["report"].evidence_ids
    assert _systems(llm, VERIFIER_PREFIX) == []
    assert "template is done" in loop.results["report"].observation


def test_exit_code_check_fails_when_the_command_never_ran(tmp_path: Path) -> None:
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json(
                [
                    _step(
                        "tests",
                        "Run pytest",
                        checks=[{"id": "exit", "kind": "exit_code", "expected_exit": 0}],
                    )
                ]
            ),
            "I ran pytest and it passed.",
            "No.",
        ],
        max_attempts=1,
    )
    plan = loop.run("run pytest")
    assert plan.steps[0].status is StepStatus.FAILED
    assert "never ran" in (loop.results["tests"].error or "")
    assert loop.results["tests"].evidence_ids


def test_correct_file_passes_with_cited_evidence(tmp_path: Path) -> None:
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json(
                [
                    _step(
                        "report",
                        "Write the report",
                        checks=[
                            {
                                "id": "body",
                                "kind": "file_contains",
                                "path": "report.md",
                                "contains": "Total",
                            }
                        ],
                    )
                ]
            ),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "report.md", "content": "Total: 3\n"},
                        )
                    ]
                )
            ),
            "Wrote report.md.",
            verdict(True, "the report has a total"),
            "Wrote the report.",
        ],
        max_attempts=1,
    )
    plan = loop.run("write the report")
    assert plan.steps[0].status is StepStatus.DONE
    result = loop.results["report"]
    assert result.verified is True
    assert result.evidence_ids
    assert result.check_results[0].passed is True
    assert sandbox.read_file("report.md") == "Total: 3\n"
    dumped = loop.ledger.dump(tmp_path / "out")
    lines = [RunRecord.model_validate_json(line) for line in dumped.read_text().splitlines()]
    assert lines[0].record == "header"
    assert lines[0].spec == EVIDENCE_CONTRACT_SPEC
    assert lines[0].version == EVIDENCE_CONTRACT_VERSION
    assert lines[0].run_id == plan.id
    bodies = [
        item.evidence
        for item in lines
        if item.evidence is not None and item.evidence.content_sha256
    ]
    assert bodies
    blob = (tmp_path / "out" / (bodies[0].content_blob or "")).read_text(encoding="utf-8")
    assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == bodies[0].content_sha256
    assert "Total: 3" in blob
    action_ids = {item.action.id for item in lines if item.action is not None}
    assert action_ids
    assert {entry.id for entry in loop.action_log} == action_ids


def test_real_failing_command_is_failed_with_evidence(tmp_path: Path) -> None:
    sandbox = LocalSandbox(tmp_path / "work")
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    _step(
                        "tests",
                        "Run the script",
                        checks=[
                            {
                                "id": "script",
                                "kind": "command",
                                "command": "python3 -c 'import sys; sys.exit(1)'",
                                "expected_exit": 0,
                            }
                        ],
                    )
                ]
            ),
            "The script finished successfully.",
            "It did not.",
        ]
    )
    loop = PlanDoVerifyLoop(
        llm=llm,
        sandbox=sandbox,
        memory=InMemoryMemoryStore(),
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        max_attempts=1,
        evidence_dir=tmp_path / "out",
    )
    plan = loop.run("run the script")
    assert plan.steps[0].status is StepStatus.FAILED
    assert "exited 1, expected 0" in (loop.results["tests"].error or "")
    assert "successfully" in loop.results["tests"].observation
    evidence = loop.ledger.for_step("tests")
    command = next(item for item in evidence if item.exit_code == 1)
    assert command.ok is False
    assert command.exit_code == 1


def test_pass_without_evidence_is_unverified(tmp_path: Path) -> None:
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("talk", "Just say it is done", checks=[])]),
            "Done.",
            verdict(True, "I said so"),
            "Unverified.",
        ],
        max_attempts=1,
    )
    plan = loop.run("say it is done")
    assert plan.steps[0].status is StepStatus.UNVERIFIED
    assert loop.results["talk"].evidence_ids == []
    assert loop.results["talk"].verified is False
    assert display_status(StepStatus.UNVERIFIED) == "unverified"


def test_disabling_evidence_keeps_a_model_only_pass(tmp_path: Path) -> None:
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("talk", "Say it is done")]),
            "Done.",
            verdict(True, "I said so"),
            "Done.",
        ],
        max_attempts=1,
    )
    loop.evidence_enabled = False
    plan = loop.run("say it is done")
    assert plan.steps[0].status is StepStatus.DONE


def test_json_schema_check_reads_the_file(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "work")
    sandbox.write_file("out.json", json.dumps({"total": 3}))
    ledger = EvidenceLedger()
    runner = CheckRunner(sandbox=sandbox, ledger=ledger)
    from swag_bot.interfaces import Step

    step = Step(
        id="shape",
        title="Check json",
        checks=[
            Check(
                id="shape",
                kind="json_schema",
                path="out.json",
                json_schema={"type": "object", "required": ["total"]},
            )
        ],
    )
    results = runner.run(step)
    assert results[0].passed is True
    sandbox.write_file("out.json", json.dumps({"other": 1}))
    again = runner.run(step)
    assert again[0].passed is False
    assert "total" in again[0].detail


def test_ledger_stores_a_long_body_past_the_old_clip(tmp_path: Path) -> None:
    ledger = EvidenceLedger(directory=tmp_path)
    body = "x" * 5000
    evidence = ledger.record_tool(
        step_id="s",
        tool="run_shell",
        arguments={"command": "echo"},
        outcome=f"exit_code=0 timed_out=false\nstdout:\n{body}\nstderr:\n",
        approved=True,
    )
    assert evidence.truncated is False
    assert evidence.stdout_sha256 == sha256_text(body)
    blob = (tmp_path / (evidence.stdout_blob or "")).read_text(encoding="utf-8")
    assert blob == body
    assert len(blob) > 2000


def test_safety_log_shows_actions_from_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    _step(
                        "write",
                        "Write hello",
                        checks=[
                            {
                                "id": "body",
                                "kind": "file_contains",
                                "path": "hello.txt",
                                "contains": "hello",
                            }
                        ],
                    )
                ]
            ),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "hello.txt", "content": "hello"},
                        )
                    ]
                )
            ),
            "wrote hello.txt",
            verdict(True, "file contains hello"),
            "Wrote hello.txt.",
        ]
    )
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            "write hello",
            "--output-dir",
            str(out),
            "--autonomy",
            "auto",
            "--max-attempts",
            "1",
        ],
    )
    text = visible(result)
    assert result.exit_code == 0, text
    assert "[done] write Write hello" in text
    assert (out / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    run_log = (out / ".swag" / "run.jsonl").read_text(encoding="utf-8")
    assert EVIDENCE_CONTRACT_SPEC in run_log
    home = ActionLog().read()
    assert home
    assert any(entry.action.summary.startswith("write_file") for entry in home)
    logged = runner.invoke(app, ["safety", "log"])
    shown = visible(logged)
    assert logged.exit_code == 0, shown
    assert "No actions logged" not in shown
    assert "write_file" in shown
    home_ids = {entry.id for entry in home}
    run_ids = {
        RunRecord.model_validate_json(line).action.id
        for line in run_log.splitlines()
        if '"record":"action"' in line or '"record": "action"' in line
    }
    assert home_ids == run_ids


def test_cli_reports_a_failed_script_with_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    _step(
                        "tests",
                        "Run the script",
                        checks=[
                            {
                                "id": "script",
                                "kind": "command",
                                "command": "python3 -c 'import sys; sys.exit(1)'",
                                "expected_exit": 0,
                            }
                        ],
                    )
                ]
            ),
            "All tests passed.",
            "The script failed.",
        ]
    )
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            "run the script",
            "--output-dir",
            str(out),
            "--autonomy",
            "auto",
            "--max-attempts",
            "1",
        ],
    )
    text = visible(result)
    assert result.exit_code == 1, text
    assert "[failed] tests Run the script" in text
    plan = json.loads((out / ".swag" / "plan.json").read_text(encoding="utf-8"))
    assert plan["steps"][0]["status"] == "failed"
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "exited 1, expected 0" in summary
    assert "evidence:" in summary
    records = [
        RunRecord.model_validate_json(line)
        for line in (out / ".swag" / "run.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    exits = [item.evidence.exit_code for item in records if item.evidence is not None]
    assert 1 in exits
    logged = visible(runner.invoke(app, ["safety", "log"]))
    assert "No actions logged" not in logged
    assert "python3 -c" in logged
