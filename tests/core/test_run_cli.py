"""``swag run`` command: options, artifacts, dry run, and factory fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.interfaces import ChatResponse, Message, ToolCall
from tests.core.support import DenyPrompter, plan_json, verdict
from tests.fakes import FakeLLMClient

runner = CliRunner()


def _visible(result: object) -> str:
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    output = getattr(result, "output", "") or ""
    return f"{stdout}\n{stderr}\n{output}"


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
    for name in ("--autonomy", "--model", "--output-dir", "--max-steps", "--dry-run"):
        assert name in result.output


def test_run_without_a_model_client_exits_2() -> None:
    result = runner.invoke(app, ["run", "say hello"])
    assert result.exit_code == 2
    assert "not implemented" in _visible(result).lower()


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
    assert len(log) == 1
    assert "write_file" in log[0]
    assert '"approver":"auto"' in log[0] or '"approver": "auto"' in log[0]
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
