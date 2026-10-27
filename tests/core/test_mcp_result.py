"""MCP task results include checks, files, and a declined stop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.config import load_settings
from swag_bot.core.cli import GoalResult, mcp_task_runner
from swag_bot.core.mcp_result import list_output_files
from swag_bot.interfaces import CheckResult
from swag_bot.onboarding.approvals import (
    MCPApprovalPrompter,
    bind_prompter,
    reset_prompter,
)
from swag_bot.onboarding.detect import BYOK_CANDIDATES, EnvironmentSnapshot


def _snapshot() -> EnvironmentSnapshot:
    keys = {env_var: False for _provider, env_var, _model in BYOK_CANDIDATES}
    return EnvironmentSnapshot(
        keys=keys,
        google_api_key_set=False,
        ollama_installed=True,
        ollama_models=["qwen2.5:7b"],
        mem_bytes=8 * 1024 * 1024 * 1024,
    )


def _patch_detect(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = _snapshot()
    monkeypatch.setattr("swag_bot.onboarding.setup.capture_environment", lambda **_k: snap)
    monkeypatch.setattr("swag_bot.onboarding.status.capture_environment", lambda **_k: snap)


def test_mcp_task_runs_first_setup_then_returns_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _patch_detect(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    script = out / "fizzbuzz.py"
    script.write_text("print('FizzBuzz')\n", encoding="utf-8")
    seen: dict[str, str] = {}

    def run(goal: str, **_kwargs: object) -> GoalResult:
        seen["model"] = load_settings().model.model
        return GoalResult(
            summary="# Summary\n\nGoal met.\n",
            output_dir=out,
            exit_code=0,
            engine_note="",
            goal_checks=(
                CheckResult(
                    check_id="goal-file",
                    passed=True,
                    evidence_ids=["ev-abc"],
                    detail="fizzbuzz.py exists",
                ),
            ),
        )

    monkeypatch.setattr("swag_bot.core.cli.execute_goal", run)
    raw = mcp_task_runner("Write fizzbuzz.py and run it with python3")
    payload = json.loads(raw)
    assert seen["model"] == "qwen2.5:7b"
    assert payload["status"] == "met"
    assert payload["goal_checks"][0]["evidence_ids"] == ["ev-abc"]
    assert payload["output_dir"] == str(out.resolve())
    files = {item["path"]: item for item in payload["files"]}
    assert files["fizzbuzz.py"]["size"] == script.stat().st_size
    assert files["fizzbuzz.py"]["content"] == "print('FizzBuzz')\n"
    assert "result" not in payload or payload.get("status") == "met"
    assert "# Summary" in payload["summary"]


def test_mcp_task_does_not_call_the_model_when_setup_cannot_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    empty = EnvironmentSnapshot(
        keys={env_var: False for _provider, env_var, _model in BYOK_CANDIDATES},
        google_api_key_set=False,
        ollama_installed=True,
        ollama_models=[],
        mem_bytes=8 * 1024 * 1024 * 1024,
    )
    monkeypatch.setattr("swag_bot.onboarding.setup.capture_environment", lambda **_k: empty)
    monkeypatch.setattr("swag_bot.onboarding.status.capture_environment", lambda **_k: empty)

    def run(*_args: object, **_kwargs: object) -> GoalResult:
        raise AssertionError("model run started")

    monkeypatch.setattr("swag_bot.core.cli.execute_goal", run)
    payload = json.loads(mcp_task_runner("Write fizzbuzz.py"))
    assert payload["status"] == "aborted"
    assert "`swag setup --auto`" in payload["summary"]
    assert payload["files"][0]["exists"] is False
    assert payload["files"][0]["content"] is None


def test_declined_approval_stops_before_the_model_and_writes_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def run(*_args: object, **_kwargs: object) -> GoalResult:
        raise AssertionError("model run started")

    monkeypatch.setattr("swag_bot.core.cli.execute_goal", run)
    monkeypatch.setattr(
        "swag_bot.core.cli.build_llm_client",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("model client built")),
    )
    token = bind_prompter(MCPApprovalPrompter(allow_risky=False, reason="declined"))
    try:
        payload = json.loads(mcp_task_runner("Write hello.txt"))
    finally:
        reset_prompter(token)
    assert payload["status"] == "not_met"
    assert "declined" in payload["summary"].lower()
    assert "declined" in payload["message"].lower()
    folder = Path(payload["output_dir"])
    summary = (folder / "summary.md").read_text(encoding="utf-8")
    assert "Goal not met." in summary
    assert "declined" in summary.lower()
    assert (folder / ".swag" / "plan.json").is_file()
    assert not list(folder.rglob("hello.txt"))


def test_missing_requested_file_is_listed_as_not_written(tmp_path: Path) -> None:
    rows = list_output_files(tmp_path, "Write missing.py")
    assert rows == [
        {
            "path": "missing.py",
            "exists": False,
            "size": None,
            "content": None,
            "note": "not written",
        }
    ]


def test_large_file_omits_content(tmp_path: Path) -> None:
    blob = tmp_path / "notes.txt"
    blob.write_bytes(b"x" * 5000)
    rows = list_output_files(tmp_path, "Write notes.txt")
    assert rows[0]["exists"] is True
    assert rows[0]["size"] == 5000
    assert rows[0]["content"] is None
    assert "omitted" in rows[0]["note"]
