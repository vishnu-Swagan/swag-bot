"""Run bundles: record, redact, replay offline, inspect, and export."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.core.bundle import BundleReplayer, replay_run
from swag_bot.core.bundle.redact import redact_text, redact_value
from swag_bot.core.bundle.replay import RunReplayer
from swag_bot.errors import SwagError
from swag_bot.interfaces import ChatResponse, Message, ToolCall
from tests.cli_output import visible
from tests.core.support import DenyPrompter, plan_json, verdict
from tests.fakes import FakeLLMClient

runner = CliRunner()

SECRET = "sk-testsecretvalue1234567890"
GITHUB = "ghp_abcdefghij1234567890"
AWS = "AKIATESTKEY0EXAMPLE1"


def _hello_plan() -> str:
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


def _hello_script(content: str = "hello", final: str = "wrote hello.txt") -> list[object]:
    return [
        _hello_plan(),
        ChatResponse(
            message=Message.assistant(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "hello.txt", "content": content},
                    )
                ]
            )
        ),
        final,
        verdict(True, "file contains hello"),
        "Wrote hello.txt.",
    ]


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses: list[object],
    args: list[str],
) -> object:
    monkeypatch.setenv("SWAG_HOME", str(tmp_path / "home"))
    llm = FakeLLMClient(responses)  # type: ignore[arg-type]
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    return runner.invoke(app, args)


def test_redact_is_idempotent_and_keeps_plain_text() -> None:
    plain = "hello token of appreciation"
    assert redact_text(plain) == plain
    secret = f"see {SECRET} and password=hunter2hunter2 and {GITHUB}"
    once = redact_text(secret)
    assert SECRET not in once
    assert "hunter2hunter2" not in once
    assert GITHUB not in once
    assert redact_text(once) == once
    cleaned = redact_value({"api_key": SECRET, "note": f"use {SECRET}"})
    assert isinstance(cleaned, dict)
    assert cleaned["api_key"] == "[REDACTED]"
    assert SECRET not in str(cleaned)


def test_recorded_replay_matches_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    result = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    text = visible(result)
    assert result.exit_code == 0, text
    bundle = out / "bundle"
    assert f"Bundle: {bundle}" in text
    assert (out / "hello.txt").read_text(encoding="utf-8") == "hello"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["spec"] == "swag-run-bundle"
    assert manifest["version"] == "1.0"
    assert manifest["model"]["model"] == "demo-model"
    assert manifest["redacted"] is True
    assert manifest["result"]["step_status"]["write"] == "done"
    replay_dir = tmp_path / "replay"
    report = replay_run(bundle, workdir=replay_dir)
    assert report.matched, report.differences
    assert report.model_mismatches == 0
    assert report.step_status == {"write": "done"}
    assert (replay_dir / "hello.txt").read_text(encoding="utf-8") == "hello"
    assert isinstance(BundleReplayer(), RunReplayer)


def test_secrets_are_absent_from_the_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "notes.txt").write_text(f"token {GITHUB}\n", encoding="utf-8")
    content = f"hello {SECRET} password=hunter2hunter2 {AWS}"
    prose = f"wrote the file {SECRET}"
    result = _run(
        tmp_path,
        monkeypatch,
        _hello_script(content, prose),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    assert SECRET in (out / "hello.txt").read_text(encoding="utf-8")
    bundle = out / "bundle"
    leaked = [
        str(path.relative_to(bundle))
        for path in bundle.rglob("*")
        if path.is_file() and _contains_secret(path)
    ]
    assert leaked == []
    blob_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (bundle / "files" / "objects").rglob("*")
        if path.is_file()
    )
    assert "[REDACTED]" in blob_text
    replay_dir = tmp_path / "replay"
    report = replay_run(bundle, workdir=replay_dir)
    assert report.matched, report.differences
    replay_blob = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in replay_dir.rglob("*")
        if path.is_file()
    )
    assert SECRET not in replay_blob
    assert GITHUB not in replay_blob
    assert AWS not in replay_blob


def test_replay_cli_inspect_and_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    recorded = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert recorded.exit_code == 0, visible(recorded)
    bundle = out / "bundle"
    inspected = runner.invoke(app, ["bundle", "inspect", str(bundle)])
    assert inspected.exit_code == 0, visible(inspected)
    info = visible(inspected)
    assert "write hello" in info
    assert "demo-model" in info
    assert "Secrets: redacted" in info
    archive = tmp_path / "run.zip"
    exported = runner.invoke(app, ["bundle", "export", str(bundle), "--output", str(archive)])
    assert exported.exit_code == 0, visible(exported)
    assert archive.is_file()
    replay_dir = tmp_path / "from-zip"
    replayed = runner.invoke(
        app,
        ["replay", str(archive), "--output-dir", str(replay_dir), "--tools", "rerun"],
    )
    assert replayed.exit_code == 0, visible(replayed)
    assert "Matched the bundle." in visible(replayed)
    assert (replay_dir / "hello.txt").read_text(encoding="utf-8") == "hello"


def test_denied_replay_stays_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("swag_bot.core.cli.build_prompter", lambda settings: DenyPrompter())
    out = tmp_path / "out"
    result = _run(
        tmp_path,
        monkeypatch,
        [
            _hello_plan(),
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
            verdict(False, "not written"),
            "Blocked.",
        ],
        [
            "run",
            "write hello",
            "--record",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 1, visible(result)
    assert not (out / "hello.txt").exists()
    replay_dir = tmp_path / "replay"
    report = replay_run(out / "bundle", workdir=replay_dir)
    assert report.matched, report.differences
    assert report.step_status["write"] == "failed"
    assert not (replay_dir / "hello.txt").exists()


def test_synthesized_evidence_and_included_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    result = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    ledger = (out / "bundle" / "evidence" / "run.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in ledger.splitlines() if line.strip()]
    assert rows[0]["record"] == "header"
    assert rows[0]["spec"] == "swag-evidence-contract"
    assert rows[0]["version"] == "1.0"
    evidence = [row["evidence"] for row in rows if row["record"] == "evidence"]
    assert evidence
    assert evidence[0]["tool"] == "write_file"
    assert evidence[0]["kind"] == "tool"
    manifest = json.loads((out / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence"]["source"] == "synthesized"

    copied = tmp_path / "copied"
    copied.mkdir()
    source = copied / "run.jsonl"
    source.write_text(
        '{"record":"header","spec":"swag-evidence-contract","version":"1.0","goal":"keep"}\n',
        encoding="utf-8",
    )
    again = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(copied),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
        ],
    )
    assert again.exit_code == 0, visible(again)
    included = copied / "bundle" / "evidence" / "run.jsonl"
    assert included.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    copied_manifest = json.loads((copied / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert copied_manifest["evidence"]["source"] == "run.jsonl"


def test_undo_tree_hash_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    out = tmp_path / "out"
    monkeypatch.setenv("SWAG_HOME", str(home))
    runs = home / "undo" / "runs"
    runs.mkdir(parents=True)
    (runs / "earlier.json").write_text(
        json.dumps(
            {
                "run_id": "earlier",
                "workdir": str(out.resolve()),
                "base_tree": "abc123",
                "checkpoints": [{"reason": "run-start", "step_id": None, "tree": "abc123"}],
            }
        ),
        encoding="utf-8",
    )
    (home / "undo" / "index.json").write_text(
        json.dumps(
            {"runs": [{"id": "earlier", "workdir": str(out.resolve()), "created_at": "t"}]}
        ),
        encoding="utf-8",
    )
    result = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    manifest = json.loads((out / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["undo"]["present"] is True
    assert manifest["undo"]["base_tree"] == "abc123"
    assert manifest["undo"]["aligned_with"] == "swag-undo-snapshot"
    trees = json.loads((out / "bundle" / "files" / "trees.json").read_text(encoding="utf-8"))
    assert trees["aligned_with"] == "swag-undo-snapshot"
    assert trees["after"]["tree"]


def test_fallback_handoff_and_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "fallback"
    fallback = _run(
        tmp_path,
        monkeypatch,
        ["not json", "still not json"],
        [
            "run",
            "do the thing",
            "--record",
            "--dry-run",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
        ],
    )
    assert fallback.exit_code == 0, visible(fallback)
    assert "PLAN FALLBACK" in visible(fallback)
    manifest = json.loads((out / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["plan_fallback"] is True
    events = [
        json.loads(line)
        for line in (out / "bundle" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["kind"] == "plan_fallback" for event in events)
    replay_dir = tmp_path / "fallback-replay"
    report = replay_run(out / "bundle", workdir=replay_dir)
    assert report.matched, report.differences
    assert report.step_status["step-1"] == "pending"

    two = plan_json(
        [
            {
                "id": "first",
                "title": "Write a",
                "instruction": "Write a.txt",
                "success_criteria": "a.txt exists",
            },
            {
                "id": "second",
                "title": "Write b",
                "instruction": "Write b.txt",
                "depends_on": ["first"],
                "success_criteria": "b.txt exists",
            },
        ]
    )

    def tool(path: str, content: str, call_id: str) -> ChatResponse:
        return ChatResponse(
            message=Message.assistant(
                tool_calls=[
                    ToolCall(
                        id=call_id,
                        name="write_file",
                        arguments={"path": path, "content": content},
                    )
                ]
            )
        )

    depended = tmp_path / "depended"
    result = _run(
        tmp_path,
        monkeypatch,
        [
            two,
            tool("a.txt", "a", "c1"),
            "wrote a",
            verdict(True, "a exists"),
            tool("b.txt", "b", "c2"),
            "wrote b",
            verdict(True, "b exists"),
            "Both files are written.",
        ],
        [
            "run",
            "write two files",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(depended),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    handoff = [
        json.loads(line)
        for line in (depended / "bundle" / "handoff.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    second = next(row for row in handoff if row["step_id"] == "second")
    assert second["depends_on"] == ["first"]
    assert second["status"] == "done"
    memory = [
        json.loads(line)
        for line in (depended / "bundle" / "memory.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    writes = [row for row in memory if row.get("op") == "add"]
    searches = [row for row in memory if row.get("op") == "search"]
    assert writes
    assert any(row["metadata"].get("run_id") for row in writes)
    assert any(row["metadata"].get("step_id") == "first" for row in writes)
    assert any(row.get("phase") == "planner" for row in searches)
    step_b = next(row for row in searches if row.get("query") == "Write b")
    assert step_b["phase"] == "step"
    assert step_b["results"]
    replayed = tmp_path / "depended-replay"
    report = replay_run(depended / "bundle", workdir=replayed)
    assert report.matched, report.differences
    assert (replayed / "a.txt").read_text(encoding="utf-8") == "a"
    assert (replayed / "b.txt").read_text(encoding="utf-8") == "b"


def test_live_replay_reports_a_difference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    result = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    other = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "other",
                        "title": "Write other",
                        "instruction": "Write other.txt",
                        "success_criteria": "other.txt contains other",
                    }
                ]
            ),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c9",
                            name="write_file",
                            arguments={"path": "other.txt", "content": "other"},
                        )
                    ]
                )
            ),
            "wrote other",
            verdict(True, "other exists"),
            "Wrote other.txt.",
        ]
    )
    replay_dir = tmp_path / "live"
    report = replay_run(out / "bundle", mode="live", llm=other, workdir=replay_dir)
    assert report.matched is False
    assert report.differences
    assert (replay_dir / "other.txt").read_text(encoding="utf-8") == "other"


def test_recorded_tools_restore_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    result = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--record",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    replay_dir = tmp_path / "canned"
    report = replay_run(out / "bundle", workdir=replay_dir, tool_mode="recorded")
    assert report.matched, report.differences
    assert (replay_dir / "hello.txt").read_text(encoding="utf-8") == "hello"


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../evil.txt", "nope")
    with pytest.raises(SwagError, match="escapes"):
        replay_run(archive)


def test_run_without_record_writes_no_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    result = _run(
        tmp_path,
        monkeypatch,
        _hello_script(),
        [
            "run",
            "write hello",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--max-attempts",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    assert not (out / "bundle").exists()


def test_config_record_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text("[bundle]\nrecord = true\n", encoding="utf-8")
    monkeypatch.setenv("SWAG_HOME", str(home))
    out = tmp_path / "out"
    llm = FakeLLMClient(_hello_script())  # type: ignore[arg-type]
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    result = runner.invoke(
        app,
        [
            "run",
            "write hello",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--model",
            "demo-model",
            "--max-attempts",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, visible(result)
    assert (out / "bundle" / "manifest.json").is_file()


def _contains_secret(path: Path) -> bool:
    raw = path.read_bytes()
    needles = (SECRET, GITHUB, AWS, "hunter2hunter2")
    return any(needle.encode() in raw for needle in needles)
