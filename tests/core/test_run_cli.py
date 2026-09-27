"""``swag run`` command: options, artifacts, dry run, and factory fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.interfaces import ChatResponse, Message, ToolCall
from tests.cli_output import visible as _visible
from tests.core.support import DenyPrompter, plan_json, verdict
from tests.fakes import FakeLLMClient

runner = CliRunner()


def _write_plan() -> str:
    return plan_json(
        [
            {
                "id": "write",
                "title": "Write hello",
                "instruction": "Write hello.txt",
                "success_criteria": "hello.txt contains hello",
            }
        ]
    )


def test_help_lists_run_options() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    text = _visible(result)
    assert "\x1b" not in text
    for name in (
        "--autonomy",
        "--model",
        "--output-dir",
        "--max-steps",
        "--dry-run",
        "--evidence",
        "--escalate",
        "--taint-mode",
        "--strict-plan",
        "--memory-mode",
    ):
        assert name in text


def test_model_errors_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    from swag_bot.models.errors import ModelError

    def fail(settings: object) -> object:
        raise ModelError("ollama is not reachable")

    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", fail)
    result = runner.invoke(app, ["run", "say hello"])
    assert result.exit_code == 1
    assert "not reachable" in _visible(result).lower()


def test_invalid_limits_exit_1() -> None:
    result = runner.invoke(app, ["run", "say hello", "--max-steps", "0"])
    assert result.exit_code == 1
    blank = runner.invoke(app, ["run", "   "])
    assert blank.exit_code == 1


def test_dry_run_writes_plan_and_does_not_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient([_write_plan()])
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["run", "write hello", "--dry-run", "--output-dir", str(out), "--model", "demo-model"],
    )
    assert result.exit_code == 0, _visible(result)
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    assert plan["goal"] == "write hello"
    assert plan["steps"][0]["status"] == "pending"
    assert (out / "action-log.jsonl").read_text(encoding="utf-8") == ""
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "Dry run" in summary
    assert "[pending] write Write hello" in _visible(result)
    assert llm.models == ["demo-model"]
    assert not (out / "hello.txt").exists()


def test_run_writes_artifacts_and_streams_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient(
        [
            _write_plan(),
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
    text = _visible(result)
    assert result.exit_code == 0, text
    assert (out / "hello.txt").read_text(encoding="utf-8") == "hello"
    assert "[done] write Write hello" in text
    assert "wrote hello.txt" in text
    log = (out / "action-log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert log
    write_lines = [line for line in log if "write_file" in line]
    assert len(write_lines) == 1
    assert '"approver":"auto"' in write_lines[0] or '"approver": "auto"' in write_lines[0]
    assert "Wrote hello.txt." in (out / "summary.md").read_text(encoding="utf-8")
    assert f"Output: {out}" in text


def test_default_output_dir_and_graphbit_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient([_write_plan()])
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", "write hello", "--dry-run", "--engine", "graphbit"])
    text = _visible(result)
    assert result.exit_code == 0, text
    assert "not installed" in text
    folders = list((tmp_path / "swag-output").iterdir())
    assert len(folders) == 1
    assert (folders[0] / "plan.json").is_file()
    assert (folders[0] / "summary.md").is_file()


def test_approval_run_prints_each_line_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient(
        [
            _write_plan(),
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
        ["run", "write hello", "--output-dir", str(out), "--max-attempts", "1"],
        input="y\n",
    )
    text = _visible(result)
    assert result.exit_code == 0, text
    assert text.count("[done] write Write hello") == 1
    assert text.count("[write] wrote hello.txt") == 1
    assert text.count("# Summary") == 1
    assert "remembered:" in text
    assert "evidence none" in text
    for line in text.splitlines():
        if "Allow this action" in line:
            assert "write_file" not in line
    assert (out / "hello.txt").read_text(encoding="utf-8") == "hello"


def test_strict_plan_exits_when_the_model_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient(["not json", "still not json"])
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    result = runner.invoke(
        app,
        ["run", "do the thing", "--strict-plan", "--output-dir", str(tmp_path / "out")],
    )
    text = _visible(result)
    assert result.exit_code == 1
    assert "PLAN FALLBACK" in text
    assert "Strict planning" in text


def test_recalled_memory_is_announced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swag_bot.core.cli import execute_goal
    from tests.fakes import InMemoryMemoryStore

    memory = InMemoryMemoryStore()
    memory.add(
        "write hello was saved in note.txt",
        metadata={
            "kind": "step",
            "run_id": "earlier",
            "step_id": "write",
            "goal": "write a note",
            "evidence_ids": ["ev-1"],
            "source": "swag",
        },
    )
    llm = FakeLLMClient([_write_plan()])
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    monkeypatch.setattr("swag_bot.core.cli.build_memory_store", lambda settings: memory)
    notes: list[str] = []
    result = execute_goal(
        "write hello",
        dry_run=True,
        output_dir=tmp_path / "out",
        announce=notes.append,
        on_event=lambda event: None,
    )
    assert result.exit_code == 0
    assert any("recalled:" in line and "earlier" in line and "ev-1" in line for line in notes)
    planner = llm.messages[0][-1].content or ""
    assert "write hello was saved in note.txt" in planner
    assert "run earlier" in planner


def test_denied_write_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLMClient(
        [
            _write_plan(),
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
            "denied",
            verdict(False, "not written", replan=False),
            "Blocked.",
        ]
    )
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    monkeypatch.setattr("swag_bot.core.cli.build_prompter", lambda settings: DenyPrompter())
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["run", "write hello", "--output-dir", str(out), "--max-attempts", "1"],
    )
    assert result.exit_code == 1, _visible(result)
    assert not (out / "hello.txt").exists()
    assert "denied" in (out / "action-log.jsonl").read_text(encoding="utf-8")


def test_unknown_engine_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLMClient([_write_plan()])
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    result = runner.invoke(
        app,
        [
            "run",
            "write hello",
            "--dry-run",
            "--engine",
            "nope",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 1
    assert "unknown workflow engine" in _visible(result)
