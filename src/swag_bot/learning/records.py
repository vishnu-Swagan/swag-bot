"""On-disk candidate records. These stay in quarantine until promotion."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CandidateStatus(StrEnum):
    """Where a distilled skill is in review."""

    QUARANTINED = "quarantined"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class CandidateRecord(BaseModel):
    """``candidate.json`` inside ``$SWAG_HOME/skill-candidates/<id>/``."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    id: str
    run_id: str
    skill_name: str
    goal: str
    varied_goal: str | None = None
    status: CandidateStatus = CandidateStatus.QUARANTINED
    created_at: str
    updated_at: str
    block_reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
