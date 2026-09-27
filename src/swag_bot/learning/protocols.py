"""Protocols for verified-run evidence and run replay.

Feature #1 (evidence ledger) and feature #10 (run bundles) are built on
other branches. This module is the contract they should satisfy. Until
those land, ``adapters.py`` supplies stubs that never report a pass, plus
file drop-ins at:

- ``$SWAG_HOME/evidence/<run_id>.json`` — :class:`VerifiedRunEvidence`
- ``$SWAG_HOME/replays/<run_id>.json`` — :class:`RecordedReplay`

A pass is trusted only when both sides agree. A replay file alone cannot
promote a skill, and an evidence file alone cannot either.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def check_run_id(run_id: str) -> str:
    """Reject ids that are not safe as a single path segment."""
    if _RUN_ID.fullmatch(run_id) is None:
        raise ValueError(
            "run id must be 1-128 letters, digits, dots, underscores, or hyphens"
        )
    return run_id


class RunStepRecord(BaseModel):
    """One step of a finished run, as skill induction sees it.

    This is intentionally smaller than ``interfaces.Step``. A ``plan.json``
    from ``swag run`` validates here; extra keys are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    instruction: str = ""
    status: str = "pending"
    observation: str = ""

    @field_validator("id", "title")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("step id and title must not be empty")
        return value.strip()

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        return value.strip().lower()


class CompletedRun(BaseModel):
    """A finished run that may be distilled into a candidate skill."""

    model_config = ConfigDict(extra="ignore")

    id: str
    goal: str
    steps: list[RunStepRecord] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        return check_run_id(value)

    @field_validator("goal")
    @classmethod
    def _goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be empty")
        return value

    def succeeded(self) -> bool:
        """True when every step finished ``done``. An empty plan did not succeed."""
        if not self.steps:
            return False
        return all(step.status == "done" for step in self.steps)


class VerifiedRunEvidence(BaseModel):
    """Whether a run passed evidence-based verification.

    ``verified`` alone is not enough. :meth:`accepted` is true only when the
    flag is set and at least one evidence id is present, matching the rule
    that a pass with no cited evidence is unverified.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str
    verified: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    detail: str = ""

    @field_validator("run_id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        return check_run_id(value)

    def cited_ids(self) -> list[str]:
        """Evidence ids that are safe to store on a skill."""
        found: list[str] = []
        for item in self.evidence_ids:
            text = item.strip()
            if _EVIDENCE_ID.fullmatch(text):
                found.append(text)
        return found

    def accepted(self) -> bool:
        """True when this run may satisfy the verification half of the gate."""
        return self.verified and bool(self.cited_ids())


class ReplayOutcome(StrEnum):
    """What a replay attempt concluded."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ReplayRequest(BaseModel):
    """Ask a replayer to run a skill's task again.

    ``varied`` is true when ``goal`` is the abstracted task rather than the
    original wording. Feature #10 should execute ``goal`` and honor ``varied``.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str
    goal: str
    skill_name: str
    varied: bool = False

    @field_validator("run_id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        return check_run_id(value)


class ReplayResult(BaseModel):
    """Outcome of one :class:`ReplayRequest`."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    outcome: ReplayOutcome
    detail: str = ""
    varied: bool = False
    goal: str = ""

    def accepted(self) -> bool:
        """True when this replay may satisfy the replay half of the gate."""
        return self.outcome is ReplayOutcome.PASSED


class RecordedReplay(BaseModel):
    """JSON shape of ``$SWAG_HOME/replays/<run_id>.json``.

    Feature #10 should write this after it actually replays the bundle.
    The file adapter does not re-execute anything; a missing file stays
    ``unavailable`` and never counts as a pass.
    """

    model_config = ConfigDict(extra="ignore")

    outcome: ReplayOutcome
    detail: str = ""


class ReplaySpec(BaseModel):
    """The replayable test stored beside a candidate skill.

    ``references/replay.json`` inside the skill. Feature #10 can execute it.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str
    goal: str
    varied_goal: str | None = None
    steps: list[RunStepRecord] = Field(default_factory=list)


class SkillProvenance(BaseModel):
    """Recorded on a promoted skill. Source run and evidence ids are required."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    source_run: str
    evidence_ids: list[str]
    verified: bool = True
    replay_outcome: str
    replay_varied: bool = False
    replay_goal: str
    candidate_id: str
    skill_name: str
    promoted_at: str

    @field_validator("evidence_ids")
    @classmethod
    def _ids(cls, value: Sequence[str]) -> list[str]:
        if not value:
            raise ValueError("promoted skills must cite evidence ids")
        return list(value)

    @field_validator("source_run", "candidate_id", "skill_name", "replay_goal")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provenance fields must not be empty")
        return value


@runtime_checkable
class RunEvidenceSource(Protocol):
    """Load verification evidence for one run.

    Feature #1 (the evidence ledger) should implement this. The stub reports
    every run as unverified.
    """

    def evidence_for(self, run_id: str) -> VerifiedRunEvidence:
        """Return evidence for ``run_id``. Do not raise merely because it is unverified."""
        ...


@runtime_checkable
class RunReplayer(Protocol):
    """Replay a run on the same task or a varied one.

    Feature #10 (run bundles) should implement this by re-executing the
    recorded bundle. The stub never returns ``passed``.
    """

    def replay(self, request: ReplayRequest) -> ReplayResult:
        """Replay ``request``. An unavailable bundle is not a pass."""
        ...
