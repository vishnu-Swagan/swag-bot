"""Distilled skills are Cowork-compatible and stay out of the active directory."""

from __future__ import annotations

from pathlib import Path

from swag_bot.interfaces import Step, StepStatus, TaskPlan
from swag_bot.learning.distill import distill, skill_name_for, vary_goal
from swag_bot.learning.protocols import CompletedRun, RunStepRecord
from swag_bot.plugins.loader import load_skill_directory


def _run(goal: str = 'Create "hello.txt" containing "hi"') -> CompletedRun:
    return CompletedRun(
        id="run-1",
        goal=goal,
        steps=[
            RunStepRecord(
                id="s1",
                title="Write the file",
                instruction="Write hello.txt with the text hi",
                status="done",
                observation="wrote hello.txt",
            )
        ],
    )


def test_plan_json_from_a_run_is_a_completed_run() -> None:
    plan = TaskPlan(
        id="run-plan",
        goal="Create hello.txt containing hi",
        steps=[
            Step(
                id="s1",
                title="Write hello",
                instruction="write hello.txt",
                status=StepStatus.DONE,
            )
        ],
    )
    run = CompletedRun.model_validate_json(plan.model_dump_json())
    assert run.succeeded() is True
    assert run.goal == "Create hello.txt containing hi"


def test_varied_goal_replaces_quotes_and_filenames() -> None:
    assert vary_goal('Create "hello.txt" containing "hi"') == "Create {{arg1}} containing {{arg2}}"
    assert vary_goal("Create hello.txt containing hi") == "Create {{file1}} containing hi"
    assert vary_goal("Summarize the notes") is None


def test_skill_file_loads_with_the_existing_skill_loader(tmp_path: Path) -> None:
    home = tmp_path
    distilled = distill(_run())
    directory = home / distilled.name
    files = distilled.files(candidate_id="cand", provenance=None)
    for relative, text in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    skill = load_skill_directory(directory)
    assert skill.meta.name == distilled.name
    assert skill.meta.license == "MIT"
    assert "hello.txt" in skill.meta.description
    assert skill.meta.metadata["source-run"] == "run-1"
    assert skill.meta.metadata["status"] == "candidate"
    assert skill.meta.metadata["evidence"] == "pending"
    assert "Write the file" in skill.instructions()
    assert "references/replay.json" in skill.resources()


def test_skill_name_stays_within_the_agent_skills_rules() -> None:
    name = skill_name_for("Create " + ("very-long-" * 20) + "report.txt", "RUN-ABCDEF-999")
    assert 1 <= len(name) <= 64
    assert name.endswith("runabcdef999")
    directory_safe = name.replace("-", "")
    assert directory_safe.isalnum()
