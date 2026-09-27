"""Skill learning uses the evidence ledger and bundle replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.config import SkillLearningMode, swag_home
from swag_bot.core.cli import execute_goal
from swag_bot.interfaces import AutonomyLevel, ChatResponse, Message, ToolCall
from swag_bot.learning.adapters import StubEvidenceSource, StubRunReplayer, replayer_for
from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.protocols import (
    CompletedRun,
    ReplayOutcome,
    ReplayRequest,
    ReplaySpec,
    RunReplayer,
)
from swag_bot.learning.runtime import (
    BundleRunReplayer,
    LedgerEvidenceSource,
    request_from_replay_spec,
)
from swag_bot.learning.service import learn_from_run, promote_candidate
from swag_bot.learning.store import skill_dir_of
from tests.core.support import plan_json, verdict
from tests.fakes import FakeLLMClient


def _write_turn(path: str, content: str) -> ChatResponse:
    return ChatResponse(
        message=Message.assistant(
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="write_file",
                    arguments={"path": path, "content": content},
                )
            ]
        )
    )


def _success_script() -> list[object]:
    return [
        plan_json(
            [
                {
                    "id": "write",
                    "title": "Write hello",
                    "instruction": "Write hello.txt",
                    "success_criteria": "hello.txt contains hello",
                }
            ]
        ),
        _write_turn("hello.txt", "hello"),
        "wrote hello.txt",
        verdict(True, "file contains hello"),
        "Wrote hello.txt.",
    ]


def test_same_task_replay_matches_and_promotion_waits_for_both(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    llm = FakeLLMClient(_success_script())
    result = execute_goal(
        "Write hello.txt",
        output_dir=out,
        client=llm,
        autonomy=AutonomyLevel.AUTO,
        memory_mode="off",
        record=True,
        max_attempts=1,
        concurrency=1,
    )
    assert result.exit_code == 0, result.summary
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    run_id = plan["id"]
    home = swag_home()
    index = json.loads((home / "bundles" / f"{run_id}.json").read_text(encoding="utf-8"))
    assert Path(index["bundle"]).is_dir()

    evidence = LedgerEvidenceSource(home).evidence_for(run_id)
    assert evidence.accepted(), evidence.detail
    assert evidence.evidence_ids

    replayer = replayer_for(home)
    assert isinstance(replayer, RunReplayer)
    replayed = replayer.replay(
        ReplayRequest(
            run_id=run_id,
            goal="Write hello.txt",
            skill_name="write-hello",
            varied=False,
        )
    )
    assert replayed.outcome is ReplayOutcome.PASSED, replayed.detail
    saved = json.loads((home / "replays" / f"{run_id}.json").read_text(encoding="utf-8"))
    assert saved["outcome"] == "passed"
    assert "detail" in saved

    varied = replayer.replay(
        ReplayRequest(
            run_id=run_id,
            goal="Write note.txt",
            skill_name="write-hello",
            varied=True,
        )
    )
    assert varied.outcome is ReplayOutcome.UNAVAILABLE
    assert varied.accepted() is False

    run = CompletedRun.model_validate(plan)
    learned = learn_from_run(
        run,
        home=home,
        mode=SkillLearningMode.REVIEW,
        evidence=StubEvidenceSource(),
        replayer=StubRunReplayer(),
    )
    assert learned.candidate is not None
    assert learned.promoted is False
    candidate_id = learned.candidate.id
    spec = ReplaySpec.model_validate_json(
        (skill_dir_of(home, learned.candidate) / "references" / "replay.json").read_text(
            encoding="utf-8"
        )
    )
    request = request_from_replay_spec(spec, skill_name=learned.candidate.skill_name, varied=True)
    assert request.run_id == run_id
    assert request.varied is True
    assert request.goal != "Write hello.txt"

    with pytest.raises(SkillLearningError, match="not verified"):
        promote_candidate(
            candidate_id,
            home=home,
            evidence=StubEvidenceSource(),
            replayer=BundleRunReplayer(home),
        )
    with pytest.raises(SkillLearningError, match="unavailable"):
        promote_candidate(
            candidate_id,
            home=home,
            evidence=LedgerEvidenceSource(home),
            replayer=StubRunReplayer(),
        )
    promoted = promote_candidate(
        candidate_id,
        home=home,
        evidence=LedgerEvidenceSource(home),
        replayer=BundleRunReplayer(home),
    )
    assert promoted.promoted is True
    assert promoted.active_path is not None
    provenance = json.loads(
        (promoted.active_path / "references" / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["source_run"] == run_id
    assert provenance["evidence_ids"]


def test_varied_live_replay_passes_when_every_step_is_done(tmp_path: Path) -> None:
    home = swag_home()
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "note",
                        "title": "Write the note",
                        "instruction": "Write note.txt",
                        "success_criteria": "note.txt contains note",
                    }
                ]
            ),
            _write_turn("note.txt", "note"),
            "wrote note.txt",
            verdict(True, "file contains note"),
            "Wrote note.txt.",
        ]
    )
    replayed = BundleRunReplayer(home, llm=llm).replay(
        ReplayRequest(
            run_id="varied-run",
            goal="Write note.txt",
            skill_name="write-note",
            varied=True,
        )
    )
    assert replayed.outcome is ReplayOutcome.PASSED, replayed.detail
    saved = json.loads((home / "replays" / "varied-run.json").read_text(encoding="utf-8"))
    assert saved == {"outcome": "passed", "detail": "live replay finished every step"}


def test_failing_check_is_marked_failed_and_handoff_cites_evidence(tmp_path: Path) -> None:
    out = tmp_path / "out"
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "write",
                        "title": "Write hello",
                        "instruction": "Write hello.txt",
                        "success_criteria": "hello.txt contains hello",
                        "checks": [
                            {
                                "id": "has-hello",
                                "kind": "file_contains",
                                "path": "hello.txt",
                                "contains": "hello",
                            }
                        ],
                    },
                    {
                        "id": "prove",
                        "title": "Prove the missing line",
                        "instruction": "Confirm the file contains the missing token",
                        "success_criteria": "the missing token is present",
                        "depends_on": ["write"],
                        "checks": [
                            {
                                "id": "has-token",
                                "kind": "file_contains",
                                "path": "hello.txt",
                                "contains": "missing-token",
                            }
                        ],
                    },
                ]
            ),
            _write_turn("hello.txt", "hello"),
            "wrote hello.txt",
            verdict(True, "hello is in the file"),
            "The token is not there.",
            verdict(True, "I think it passed"),
        ]
    )
    result = execute_goal(
        "Write hello.txt and then prove a missing token",
        output_dir=out,
        client=llm,
        autonomy=AutonomyLevel.AUTO,
        memory_mode="off",
        record=True,
        max_attempts=1,
        concurrency=1,
    )
    assert result.exit_code == 1
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    statuses = {step["id"]: step["status"] for step in plan["steps"]}
    assert statuses["write"] == "done"
    assert statuses["prove"] == "failed"
    ledger = (out / "run.jsonl").read_text(encoding="utf-8")
    assert '"passed":false' in ledger or '"passed": false' in ledger
    prompts = "\n".join(
        message.content or "" for turn in llm.messages for message in turn
    )
    assert "evidence: ev-" in prompts
    assert "evidence: (none)" not in prompts
    home = swag_home()
    evidence = LedgerEvidenceSource(home).evidence_for(plan["id"])
    assert evidence.verified is False
    assert evidence.detail == "a check failed"
