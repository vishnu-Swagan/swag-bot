"""CLI: unverified runs stay quarantined; verified replays can be promoted."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.config import (
    Settings,
    SkillLearningMode,
    SkillLearningSettings,
    SkillReplayTask,
    load_settings,
    save_settings,
)
from swag_bot.learning.protocols import CompletedRun
from tests.cli_output import visible

runner = CliRunner()


def _run_file(directory: Path, run_id: str, *, status: str = "done") -> Path:
    path = directory / f"{run_id}.json"
    payload = {
        "id": run_id,
        "goal": "Create hello.txt containing hi",
        "steps": [
            {
                "id": "s1",
                "title": "Write the file",
                "instruction": "Write hello.txt with the text hi",
                "status": status,
                "observation": "wrote hello.txt",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _evidence_file(directory: Path, run_id: str, *, verified: bool = True) -> Path:
    path = directory / f"{run_id}-evidence.json"
    payload = {
        "run_id": run_id,
        "verified": verified,
        "evidence_ids": ["ev-1"] if verified else [],
        "detail": "checks cited the ledger" if verified else "no ledger entries",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _replay_file(directory: Path, *, outcome: str = "passed") -> Path:
    path = directory / "replay.json"
    payload = {"outcome": outcome, "detail": "replayed the bundle"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_defaults_leave_learning_in_review(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.toml")
    assert settings.skill_learning.mode is SkillLearningMode.REVIEW
    assert settings.skill_learning.replay is SkillReplayTask.SAME


def test_skill_help_lists_review_commands() -> None:
    result = runner.invoke(app, ["skill", "--help"])
    text = visible(result)
    assert result.exit_code == 0
    for name in ("learn", "candidates", "promote", "reject", "recheck", "list"):
        assert name in text


def test_doctor_shows_the_learning_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SWAG_HOME", str(tmp_path))
    result = runner.invoke(app, ["doctor"])
    text = visible(result)
    assert result.exit_code == 0
    assert "skill_learning.mode" in text
    assert "review" in text


def test_unverified_cli_run_never_activates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    monkeypatch.chdir(work)
    run = _run_file(work, "run-unverified")
    learned = runner.invoke(app, ["skill", "learn", str(run)])
    text = visible(learned)
    assert learned.exit_code == 0, text
    assert "quarantined" in text
    assert "not active" in text
    assert not (home / "skills").exists()

    listed = runner.invoke(app, ["skill", "candidates"])
    listed_text = visible(listed)
    assert listed.exit_code == 0
    assert "run-unverified" in listed_text
    candidate_id = _candidate_id(home)

    promoted = runner.invoke(app, ["skill", "promote", candidate_id])
    promoted_text = visible(promoted)
    assert promoted.exit_code == 1
    assert "not promoted" in promoted_text
    assert "not verified" in promoted_text
    assert not (home / "skills").exists()

    skills = runner.invoke(app, ["skill", "list"])
    assert skills.exit_code == 0
    assert "no skills found" in visible(skills)


def test_verified_replay_cli_promotes_with_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    monkeypatch.chdir(work)
    run = _run_file(work, "run-ok")
    evidence = _evidence_file(work, "run-ok")
    replay = _replay_file(work)
    learned = runner.invoke(
        app,
        ["skill", "learn", str(run), "--evidence", str(evidence), "--replay", str(replay)],
    )
    learned_text = visible(learned)
    assert learned.exit_code == 0, learned_text
    assert "quarantined" in learned_text
    assert not (home / "skills").exists()
    candidate_id = _candidate_id(home)

    promoted = runner.invoke(app, ["skill", "promote", candidate_id])
    promoted_text = visible(promoted)
    assert promoted.exit_code == 0, promoted_text
    assert "promoted" in promoted_text
    assert "source run: run-ok" in promoted_text
    assert "ev-1" in promoted_text

    run_model = CompletedRun.model_validate_json(run.read_text(encoding="utf-8"))
    assert run_model.succeeded()
    skills = runner.invoke(app, ["skill", "list"])
    assert skills.exit_code == 0
    skill_dirs = list((home / "skills").iterdir())
    assert len(skill_dirs) == 1
    skill_md = (skill_dirs[0] / "SKILL.md").read_text(encoding="utf-8")
    provenance = json.loads(
        (skill_dirs[0] / "references" / "provenance.json").read_text(encoding="utf-8")
    )
    assert "source-run:" in skill_md
    assert "run-ok" in skill_md
    assert provenance["source_run"] == "run-ok"
    assert provenance["evidence_ids"] == ["ev-1"]
    assert skill_dirs[0].name in visible(skills)

    rejected = runner.invoke(app, ["skill", "reject", candidate_id])
    assert rejected.exit_code == 0
    assert "rejected" in visible(rejected)
    assert list((home / "skills").iterdir()) == []


def test_auto_mode_promotes_from_learn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    save_settings(
        Settings(skill_learning=SkillLearningSettings(mode=SkillLearningMode.AUTO)),
    )
    run = _run_file(work, "run-auto")
    evidence = _evidence_file(work, "run-auto")
    replay = _replay_file(work)
    learned = runner.invoke(
        app,
        ["skill", "learn", str(run), "--evidence", str(evidence), "--replay", str(replay)],
    )
    text = visible(learned)
    assert learned.exit_code == 0, text
    assert "promoted" in text
    assert "source run: run-auto" in text
    assert list((home / "skills").iterdir())


def test_reject_and_recheck_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    save_settings(Settings(skill_learning=SkillLearningSettings(mode=SkillLearningMode.AUTO)))
    run = _run_file(work, "run-recheck")
    evidence = _evidence_file(work, "run-recheck")
    replay = _replay_file(work, outcome="passed")
    learned = runner.invoke(
        app,
        ["skill", "learn", str(run), "--evidence", str(evidence), "--replay", str(replay)],
    )
    assert learned.exit_code == 0, visible(learned)
    skill_dir = next((home / "skills").iterdir())
    kept = runner.invoke(app, ["skill", "recheck", skill_dir.name])
    assert kept.exit_code == 0, visible(kept)
    assert "still active" in visible(kept)

    failed = {"outcome": "failed", "detail": "varied task failed"}
    replay.write_text(json.dumps(failed), encoding="utf-8")
    installed = home / "replays" / "run-recheck.json"
    installed.write_text(replay.read_text(encoding="utf-8"), encoding="utf-8")
    demoted = runner.invoke(app, ["skill", "recheck", skill_dir.name])
    assert demoted.exit_code == 0, visible(demoted)
    assert "demoted" in visible(demoted)
    assert list((home / "skills").iterdir()) == []


def _candidate_id(home: Path) -> str:
    folders = [
        path
        for path in (home / "skill-candidates").iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(folders) == 1
    return folders[0].name
