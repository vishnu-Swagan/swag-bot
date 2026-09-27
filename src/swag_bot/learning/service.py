"""Distill runs into quarantined skills and promote them only through the gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from swag_bot.config import SkillLearningMode, SkillReplayTask
from swag_bot.learning.distill import DistilledSkill, description_for, distill
from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.gate import decide
from swag_bot.learning.protocols import (
    CompletedRun,
    ReplayOutcome,
    ReplayRequest,
    ReplaySpec,
    RunEvidenceSource,
    RunReplayer,
    SkillProvenance,
)
from swag_bot.learning.records import CandidateRecord, CandidateStatus
from swag_bot.learning.store import (
    active_skill_dir,
    find_open_candidate,
    list_records,
    load_record,
    publish_skill,
    read_provenance,
    remove_active_skill,
    save_record,
    skill_dir_of,
    write_quarantine,
)


@dataclass(frozen=True)
class SkillLearningResult:
    """What ``learn_from_run`` or ``promote_candidate`` did."""

    candidate: CandidateRecord | None
    promoted: bool
    active_path: Path | None
    reason: str


@dataclass(frozen=True)
class RecheckResult:
    """What a later replay did to an already promoted skill."""

    skill_name: str
    demoted: bool
    reason: str


def learn_from_run(
    run: CompletedRun,
    *,
    home: Path,
    mode: SkillLearningMode,
    evidence: RunEvidenceSource,
    replayer: RunReplayer,
    replay_task: SkillReplayTask = SkillReplayTask.SAME,
) -> SkillLearningResult:
    """Distill ``run`` into quarantine. Promote only in ``auto`` mode, and only via the gate.

    An unverified run can become a candidate. It cannot become an active skill.
    ``off`` writes nothing.
    """
    if mode is SkillLearningMode.OFF:
        return SkillLearningResult(
            candidate=None,
            promoted=False,
            active_path=None,
            reason="skill learning is off",
        )
    if not run.succeeded():
        return SkillLearningResult(
            candidate=None,
            promoted=False,
            active_path=None,
            reason="run did not succeed; no candidate written",
        )
    existing = find_open_candidate(home, run.id)
    if existing is not None and existing.status is CandidateStatus.PROMOTED:
        return SkillLearningResult(
            candidate=existing,
            promoted=True,
            active_path=active_skill_dir(home, existing.skill_name),
            reason="already promoted",
        )
    if existing is None:
        existing = _create_candidate(home, run)
    if mode is not SkillLearningMode.AUTO:
        return SkillLearningResult(
            candidate=existing,
            promoted=False,
            active_path=None,
            reason="candidate quarantined; promote after verification and a passing replay",
        )
    try:
        return promote_candidate(
            existing.id,
            home=home,
            evidence=evidence,
            replayer=replayer,
            replay_task=replay_task,
        )
    except SkillLearningError as exc:
        current = load_record(home, existing.id)
        return SkillLearningResult(
            candidate=current,
            promoted=False,
            active_path=None,
            reason=str(exc),
        )


def promote_candidate(
    candidate_id: str,
    *,
    home: Path,
    evidence: RunEvidenceSource,
    replayer: RunReplayer,
    replay_task: SkillReplayTask = SkillReplayTask.SAME,
) -> SkillLearningResult:
    """Move a candidate into ``$SWAG_HOME/skills`` when the gate allows it.

    The gate is evaluated again even if the record already says promoted.
    A closed gate removes any active copy and leaves the candidate quarantined.
    """
    record = load_record(home, candidate_id)
    if record.status is CandidateStatus.REJECTED:
        raise SkillLearningError(f"candidate {record.id} was rejected")
    loaded = evidence.evidence_for(record.run_id)
    request = _replay_request(record, replay_task)
    replayed = replayer.replay(request)
    decision = decide(record.run_id, loaded, replayed)
    if not decision.allowed:
        remove_active_skill(home, record.skill_name)
        blocked = record.model_copy(
            update={
                "status": CandidateStatus.QUARANTINED,
                "block_reason": decision.explain(),
                "evidence_ids": loaded.cited_ids(),
                "updated_at": _now(),
            }
        )
        save_record(home, blocked)
        raise SkillLearningError(decision.explain())
    provenance = SkillProvenance(
        source_run=record.run_id,
        evidence_ids=loaded.cited_ids(),
        verified=True,
        replay_outcome=replayed.outcome.value,
        replay_varied=replayed.varied,
        replay_goal=replayed.goal or request.goal,
        candidate_id=record.id,
        skill_name=record.skill_name,
        promoted_at=_now(),
    )
    distilled = _distilled_from_disk(home, record)
    files = distilled.files(candidate_id=record.id, provenance=provenance)
    path = publish_skill(
        home,
        record.skill_name,
        files,
        decision=decision,
        provenance=provenance,
    )
    promoted = record.model_copy(
        update={
            "status": CandidateStatus.PROMOTED,
            "block_reason": "",
            "evidence_ids": list(provenance.evidence_ids),
            "updated_at": _now(),
        }
    )
    save_record(home, promoted)
    return SkillLearningResult(
        candidate=promoted,
        promoted=True,
        active_path=path,
        reason=decision.explain(),
    )


def reject_candidate(candidate_id: str, *, home: Path) -> CandidateRecord:
    """Keep the review copy and drop any active skill for this candidate."""
    record = load_record(home, candidate_id)
    if record.status is CandidateStatus.PROMOTED or _active_matches(home, record):
        remove_active_skill(home, record.skill_name)
    rejected = record.model_copy(
        update={
            "status": CandidateStatus.REJECTED,
            "block_reason": "rejected",
            "updated_at": _now(),
        }
    )
    save_record(home, rejected)
    return rejected


def list_candidates(home: Path, *, include_closed: bool = False) -> list[CandidateRecord]:
    """Quarantined candidates, or every status when ``include_closed`` is set."""
    records = list_records(home)
    if include_closed:
        return records
    return [item for item in records if item.status is CandidateStatus.QUARANTINED]


def recheck_skill(
    skill_name: str,
    *,
    home: Path,
    replayer: RunReplayer,
    replay_task: SkillReplayTask = SkillReplayTask.SAME,
) -> RecheckResult:
    """Demote a promoted skill when a later replay fails.

    An unavailable replay does not demote. Promotion requires a pass; demotion
    requires a failure, so a missing feature #10 bundle does not wipe skills.
    """
    directory = active_skill_dir(home, skill_name)
    provenance = read_provenance(directory)
    if provenance is None:
        raise SkillLearningError(f"{skill_name} has no learning provenance")
    if provenance.skill_name != skill_name:
        raise SkillLearningError("provenance skill name does not match the directory")
    record = _record_for_provenance(home, provenance)
    request = _recheck_request(record, provenance, skill_name, replay_task)
    replayed = replayer.replay(request)
    if replayed.outcome is ReplayOutcome.UNAVAILABLE:
        return RecheckResult(
            skill_name=skill_name,
            demoted=False,
            reason="replay is unavailable",
        )
    if replayed.accepted() and replayed.run_id == provenance.source_run:
        return RecheckResult(skill_name=skill_name, demoted=False, reason="replay passed")
    remove_active_skill(home, skill_name)
    reason = "replay failed" if not replayed.accepted() else "replay is for a different run"
    if record is not None and record.status is not CandidateStatus.REJECTED:
        save_record(
            home,
            record.model_copy(
                update={
                    "status": CandidateStatus.QUARANTINED,
                    "block_reason": reason,
                    "updated_at": _now(),
                }
            ),
        )
    return RecheckResult(skill_name=skill_name, demoted=True, reason=reason)


def _create_candidate(home: Path, run: CompletedRun) -> CandidateRecord:
    distilled = distill(run)
    now = _now()
    record = CandidateRecord(
        id=uuid4().hex,
        run_id=run.id,
        skill_name=distilled.name,
        goal=distilled.replay_spec.goal,
        varied_goal=distilled.varied_goal,
        status=CandidateStatus.QUARANTINED,
        created_at=now,
        updated_at=now,
    )
    write_quarantine(home, record, distilled.files(candidate_id=record.id, provenance=None))
    return record


def _distilled_from_disk(home: Path, record: CandidateRecord) -> DistilledSkill:
    """Rebuild a skill from the quarantined review copy.

    Promotion re-renders ``SKILL.md`` so provenance is written on the active
    copy. The instruction body is the one a person already reviewed.
    """
    skill_dir = skill_dir_of(home, record)
    replay_path = skill_dir / "references" / "replay.json"
    body_path = skill_dir / "SKILL.md"
    if not replay_path.is_file() or not body_path.is_file():
        raise SkillLearningError(f"candidate {record.id} is missing its skill files")
    try:
        spec = ReplaySpec.model_validate_json(replay_path.read_text(encoding="utf-8"))
        raw_body = body_path.read_text(encoding="utf-8")
    except (OSError, ValidationError) as exc:
        raise SkillLearningError(f"candidate {record.id} has an unreadable skill") from exc
    body = _body_after_frontmatter(raw_body)
    if not body.strip():
        raise SkillLearningError(f"candidate {record.id} is missing SKILL.md")
    return DistilledSkill(
        name=record.skill_name,
        description=description_for(record.goal),
        body=body,
        varied_goal=record.varied_goal,
        replay_spec=spec,
    )


def _body_after_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).strip() + "\n"
    return text


def _recheck_request(
    record: CandidateRecord | None,
    provenance: SkillProvenance,
    skill_name: str,
    replay_task: SkillReplayTask,
) -> ReplayRequest:
    if record is not None:
        return _replay_request(record, replay_task)
    return ReplayRequest(
        run_id=provenance.source_run,
        goal=provenance.replay_goal,
        skill_name=skill_name,
        varied=replay_task is SkillReplayTask.VARIED and provenance.replay_varied,
    )


def _replay_request(record: CandidateRecord, replay_task: SkillReplayTask) -> ReplayRequest:
    if replay_task is SkillReplayTask.VARIED and record.varied_goal:
        return ReplayRequest(
            run_id=record.run_id,
            goal=record.varied_goal,
            skill_name=record.skill_name,
            varied=True,
        )
    return ReplayRequest(
        run_id=record.run_id,
        goal=record.goal,
        skill_name=record.skill_name,
        varied=False,
    )


def _record_for_provenance(home: Path, provenance: SkillProvenance) -> CandidateRecord | None:
    try:
        return load_record(home, provenance.candidate_id)
    except SkillLearningError:
        return None


def _active_matches(home: Path, record: CandidateRecord) -> bool:
    provenance = _safe_provenance(active_skill_dir(home, record.skill_name))
    return provenance is not None and provenance.candidate_id == record.id


def _safe_provenance(directory: Path) -> SkillProvenance | None:
    if not directory.is_dir():
        return None
    return read_provenance(directory)


def _now() -> str:
    return datetime.now(UTC).isoformat()
