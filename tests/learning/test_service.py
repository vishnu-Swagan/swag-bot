"""An unverified run never becomes an active skill. A verified replay does."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.config import SkillLearningMode, SkillReplayTask
from swag_bot.learning.adapters import StubEvidenceSource, StubRunReplayer
from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.gate import GateDecision
from swag_bot.learning.protocols import (
    CompletedRun,
    ReplayOutcome,
    ReplayRequest,
    ReplayResult,
    SkillProvenance,
    VerifiedRunEvidence,
)
from swag_bot.learning.records import CandidateStatus
from swag_bot.learning.service import (
    learn_from_run,
    promote_candidate,
    recheck_skill,
    reject_candidate,
)
from swag_bot.learning.store import publish_skill
from swag_bot.plugins.catalog import discover_standalone_skills
from swag_bot.plugins.loader import load_skill_directory


class StaticEvidence:
    """Evidence source double. One record, keyed by its run id."""

    def __init__(self, evidence: VerifiedRunEvidence) -> None:
        self.evidence = evidence
        self.calls: list[str] = []

    def evidence_for(self, run_id: str) -> VerifiedRunEvidence:
        self.calls.append(run_id)
        if self.evidence.run_id != run_id:
            return VerifiedRunEvidence(run_id=run_id, verified=False)
        return self.evidence


class ScriptedReplayer:
    """Replayer double. ``require_varied`` forces a failure on the other kind of task."""

    def __init__(
        self,
        outcome: ReplayOutcome,
        *,
        require_varied: bool | None = None,
    ) -> None:
        self.outcome = outcome
        self.require_varied = require_varied
        self.requests: list[ReplayRequest] = []

    def replay(self, request: ReplayRequest) -> ReplayResult:
        self.requests.append(request)
        outcome = self.outcome
        if self.require_varied is True and not request.varied:
            outcome = ReplayOutcome.FAILED
        if self.require_varied is False and request.varied:
            outcome = ReplayOutcome.FAILED
        return ReplayResult(
            run_id=request.run_id,
            outcome=outcome,
            detail="scripted",
            varied=request.varied,
            goal=request.goal,
        )


def _run(
    run_id: str = "run-1",
    *,
    goal: str = "Create hello.txt containing hi",
    status: str = "done",
) -> CompletedRun:
    return CompletedRun(
        id=run_id,
        goal=goal,
        steps=[
            {
                "id": "s1",
                "title": "Write the file",
                "instruction": "Write hello.txt with the text hi",
                "status": status,
                "observation": "wrote hello.txt",
            }
        ],
    )


def _verified(run_id: str = "run-1") -> VerifiedRunEvidence:
    return VerifiedRunEvidence(
        run_id=run_id,
        verified=True,
        evidence_ids=["ev-1", "ev-2"],
        detail="every check cited the ledger",
    )


def _active(home: Path) -> list[Path]:
    root = home / "skills"
    if not root.exists():
        return []
    return [path for path in root.iterdir() if path.is_dir()]


def test_unverified_run_never_produces_an_active_skill(tmp_path: Path) -> None:
    replayer = ScriptedReplayer(ReplayOutcome.PASSED)
    result = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.AUTO,
        evidence=StubEvidenceSource(),
        replayer=replayer,
    )
    assert result.promoted is False
    assert result.candidate is not None
    assert result.candidate.status is CandidateStatus.QUARANTINED
    assert "not verified" in result.reason
    assert _active(tmp_path) == []
    assert discover_standalone_skills(home=tmp_path, cwd=tmp_path) == []
    quarantined = tmp_path / "skill-candidates" / result.candidate.id
    assert (quarantined / result.candidate.skill_name / "SKILL.md").is_file()

    with pytest.raises(SkillLearningError, match="not verified"):
        promote_candidate(
            result.candidate.id,
            home=tmp_path,
            evidence=StubEvidenceSource(),
            replayer=ScriptedReplayer(ReplayOutcome.PASSED),
        )
    assert _active(tmp_path) == []


def test_verified_run_without_a_passing_replay_stays_quarantined(tmp_path: Path) -> None:
    result = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.AUTO,
        evidence=StaticEvidence(_verified()),
        replayer=StubRunReplayer(),
    )
    assert result.promoted is False
    assert result.candidate is not None
    assert "unavailable" in result.reason
    assert _active(tmp_path) == []

    with pytest.raises(SkillLearningError, match="replay failed"):
        promote_candidate(
            result.candidate.id,
            home=tmp_path,
            evidence=StaticEvidence(_verified()),
            replayer=ScriptedReplayer(ReplayOutcome.FAILED),
        )
    assert _active(tmp_path) == []


def test_verified_replayed_run_produces_an_active_skill(tmp_path: Path) -> None:
    evidence = StaticEvidence(_verified())
    reviewed = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.REVIEW,
        evidence=evidence,
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert reviewed.promoted is False
    assert reviewed.candidate is not None
    assert evidence.calls == []
    assert _active(tmp_path) == []

    promoted = promote_candidate(
        reviewed.candidate.id,
        home=tmp_path,
        evidence=evidence,
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert promoted.promoted is True
    assert promoted.active_path is not None
    skill_dir = promoted.active_path
    skill = load_skill_directory(skill_dir)
    assert skill.meta.metadata["source-run"] == "run-1"
    assert skill.meta.metadata["evidence"] == "ev-1,ev-2"
    assert skill.meta.metadata["status"] == "promoted"
    raw = (skill_dir / "references" / "provenance.json").read_text(encoding="utf-8")
    provenance = json.loads(raw)
    assert provenance["source_run"] == "run-1"
    assert provenance["evidence_ids"] == ["ev-1", "ev-2"]
    assert provenance["verified"] is True
    assert provenance["replay_outcome"] == "passed"
    visible = discover_standalone_skills(home=tmp_path, cwd=tmp_path)
    assert [item.meta.name for item in visible] == [skill.meta.name]
    assert (tmp_path / "skill-candidates" / reviewed.candidate.id / "candidate.json").is_file()


def test_auto_mode_promotes_only_after_both_gates(tmp_path: Path) -> None:
    result = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.AUTO,
        evidence=StaticEvidence(_verified()),
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert result.promoted is True
    assert result.active_path is not None
    assert result.active_path.is_dir()
    provenance = SkillProvenance.model_validate_json(
        (result.active_path / "references" / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance.source_run == "run-1"
    assert provenance.evidence_ids == ["ev-1", "ev-2"]


def test_failed_run_and_off_mode_write_nothing(tmp_path: Path) -> None:
    failed = learn_from_run(
        _run(status="failed"),
        home=tmp_path,
        mode=SkillLearningMode.AUTO,
        evidence=StaticEvidence(_verified()),
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert failed.candidate is None
    assert "did not succeed" in failed.reason
    assert not (tmp_path / "skill-candidates").exists()
    assert _active(tmp_path) == []

    disabled = learn_from_run(
        _run("run-2"),
        home=tmp_path,
        mode=SkillLearningMode.OFF,
        evidence=StaticEvidence(_verified("run-2")),
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert disabled.candidate is None
    assert disabled.reason == "skill learning is off"
    assert _active(tmp_path) == []


def test_reject_blocks_promotion_and_removes_an_active_skill(tmp_path: Path) -> None:
    learned = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.AUTO,
        evidence=StaticEvidence(_verified()),
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert learned.candidate is not None
    assert _active(tmp_path)
    rejected = reject_candidate(learned.candidate.id, home=tmp_path)
    assert rejected.status is CandidateStatus.REJECTED
    assert _active(tmp_path) == []
    with pytest.raises(SkillLearningError, match="rejected"):
        promote_candidate(
            learned.candidate.id,
            home=tmp_path,
            evidence=StaticEvidence(_verified()),
            replayer=ScriptedReplayer(ReplayOutcome.PASSED),
        )
    assert _active(tmp_path) == []


def test_varied_replay_is_what_the_gate_runs_when_configured(tmp_path: Path) -> None:
    replayer = ScriptedReplayer(ReplayOutcome.PASSED, require_varied=True)
    learned = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.REVIEW,
        evidence=StaticEvidence(_verified()),
        replayer=replayer,
        replay_task=SkillReplayTask.VARIED,
    )
    assert learned.candidate is not None
    assert learned.candidate.varied_goal == "Create {{file1}} containing hi"
    promoted = promote_candidate(
        learned.candidate.id,
        home=tmp_path,
        evidence=StaticEvidence(_verified()),
        replayer=replayer,
        replay_task=SkillReplayTask.VARIED,
    )
    assert promoted.promoted is True
    assert replayer.requests[-1].varied is True
    assert replayer.requests[-1].goal == "Create {{file1}} containing hi"


def test_recheck_demotes_a_failed_replay_and_ignores_an_unavailable_one(tmp_path: Path) -> None:
    learned = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.AUTO,
        evidence=StaticEvidence(_verified()),
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert learned.candidate is not None
    name = learned.candidate.skill_name
    kept = recheck_skill(name, home=tmp_path, replayer=StubRunReplayer())
    assert kept.demoted is False
    assert _active(tmp_path)

    demoted = recheck_skill(
        name,
        home=tmp_path,
        replayer=ScriptedReplayer(ReplayOutcome.FAILED),
    )
    assert demoted.demoted is True
    assert _active(tmp_path) == []
    visible = discover_standalone_skills(home=tmp_path, cwd=tmp_path)
    assert visible == []


def test_promoting_again_without_evidence_removes_the_active_skill(tmp_path: Path) -> None:
    learned = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.AUTO,
        evidence=StaticEvidence(_verified()),
        replayer=ScriptedReplayer(ReplayOutcome.PASSED),
    )
    assert learned.candidate is not None
    with pytest.raises(SkillLearningError, match="not verified"):
        promote_candidate(
            learned.candidate.id,
            home=tmp_path,
            evidence=StubEvidenceSource(),
            replayer=ScriptedReplayer(ReplayOutcome.PASSED),
        )
    assert _active(tmp_path) == []


def test_publish_refuses_a_closed_gate(tmp_path: Path) -> None:
    decision = GateDecision(allowed=False, reasons=("run is not verified",))
    provenance = SkillProvenance(
        source_run="run-1",
        evidence_ids=["ev-1"],
        verified=True,
        replay_outcome="passed",
        replay_goal="Create hello.txt containing hi",
        candidate_id="cand",
        skill_name="create-hello",
        promoted_at="2026-09-28T00:00:00+00:00",
    )
    with pytest.raises(SkillLearningError, match="did not allow"):
        publish_skill(
            tmp_path,
            "create-hello",
            {"SKILL.md": "---\nname: create-hello\n---\n"},
            decision=decision,
            provenance=provenance,
        )
    assert _active(tmp_path) == []


def test_learning_the_same_run_twice_does_not_duplicate_it(tmp_path: Path) -> None:
    evidence = StaticEvidence(_verified())
    replayer = ScriptedReplayer(ReplayOutcome.PASSED)
    first = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.REVIEW,
        evidence=evidence,
        replayer=replayer,
    )
    second = learn_from_run(
        _run(),
        home=tmp_path,
        mode=SkillLearningMode.REVIEW,
        evidence=evidence,
        replayer=replayer,
    )
    assert first.candidate is not None
    assert second.candidate is not None
    assert first.candidate.id == second.candidate.id
    folders = [
        path
        for path in (tmp_path / "skill-candidates").iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(folders) == 1
