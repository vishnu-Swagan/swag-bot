"""Evidence and replay adapters for the skill-learning gate.

``LedgerEvidenceSource`` and ``BundleRunReplayer`` are what ``swag skill``
uses. The file drop-ins remain for a run that was not recorded as a bundle.
``StubEvidenceSource`` and ``StubRunReplayer`` never report a pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.protocols import (
    RecordedReplay,
    ReplayOutcome,
    ReplayRequest,
    ReplayResult,
    VerifiedRunEvidence,
    check_run_id,
)
from swag_bot.learning.runtime import BundleRunReplayer, LedgerEvidenceSource


class StubEvidenceSource:
    """Every run is unverified. Feature #1 replaces this."""

    def evidence_for(self, run_id: str) -> VerifiedRunEvidence:
        safe = _safe_run_id(run_id)
        return VerifiedRunEvidence(
            run_id=safe,
            verified=False,
            evidence_ids=[],
            detail="no evidence ledger; feature #1 has not verified this run",
        )


class StubRunReplayer:
    """Replay is unavailable, which is not a pass. Feature #10 replaces this."""

    def replay(self, request: ReplayRequest) -> ReplayResult:
        return ReplayResult(
            run_id=request.run_id,
            outcome=ReplayOutcome.UNAVAILABLE,
            detail="run replay is not available until feature #10 lands",
            varied=request.varied,
            goal=request.goal,
        )


class FileEvidenceSource:
    """Read ``<directory>/<run_id>.json``, or report the run unverified."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._stub = StubEvidenceSource()

    def evidence_for(self, run_id: str) -> VerifiedRunEvidence:
        safe = _safe_run_id(run_id)
        path = self._directory / f"{safe}.json"
        if not path.is_file():
            return self._stub.evidence_for(safe)
        payload = _read_object(path)
        file_run = payload.get("run_id")
        if file_run != safe:
            return VerifiedRunEvidence(
                run_id=safe,
                verified=False,
                evidence_ids=[],
                detail="evidence file run_id does not match this run",
            )
        try:
            return VerifiedRunEvidence.model_validate(payload)
        except ValidationError as exc:
            raise SkillLearningError(f"{path}: invalid evidence ({exc})") from exc


class FileRunReplayer:
    """Read ``<directory>/<run_id>.json``. A missing file is unavailable, not a pass.

    The JSON is a recorded outcome (see :class:`RecordedReplay`). It is the
    seam feature #10 should write after a real replay. This class does not
    re-execute the task.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._stub = StubRunReplayer()

    def replay(self, request: ReplayRequest) -> ReplayResult:
        path = self._directory / f"{request.run_id}.json"
        if not path.is_file():
            return self._stub.replay(request)
        payload = _normalize_replay(path, _read_object(path))
        try:
            recorded = RecordedReplay.model_validate(payload)
        except ValidationError as exc:
            raise SkillLearningError(f"{path}: invalid replay outcome ({exc})") from exc
        return ReplayResult(
            run_id=request.run_id,
            outcome=recorded.outcome,
            detail=recorded.detail,
            varied=request.varied,
            goal=request.goal,
        )


def evidence_dir(home: Path) -> Path:
    """Directory of per-run evidence JSON files."""
    return home / "evidence"


def replay_dir(home: Path) -> Path:
    """Directory of per-run replay outcome JSON files."""
    return home / "replays"


def evidence_source_for(home: Path) -> LedgerEvidenceSource:
    """Bundle ledger when a run was recorded, otherwise the evidence drop-in."""
    return LedgerEvidenceSource(home)


def replayer_for(home: Path) -> BundleRunReplayer:
    """Replay the recorded bundle. A drop-in file is used only when no bundle exists."""
    return BundleRunReplayer(home)


def install_evidence(home: Path, run_id: str, source: Path) -> Path:
    """Copy an evidence JSON into the home ledger under ``run_id``."""
    safe = _safe_run_id(run_id)
    payload = _read_object(source)
    file_run = payload.get("run_id")
    if isinstance(file_run, str) and file_run != safe:
        raise SkillLearningError(f"evidence run_id {file_run!r} does not match run {safe!r}")
    payload["run_id"] = safe
    try:
        VerifiedRunEvidence.model_validate(payload)
    except ValidationError as exc:
        raise SkillLearningError(f"invalid evidence file: {exc}") from exc
    destination = evidence_dir(home) / f"{safe}.json"
    _write_json(destination, payload)
    return destination


def install_replay(home: Path, run_id: str, source: Path) -> Path:
    """Copy a replay outcome JSON into the home replay directory."""
    safe = _safe_run_id(run_id)
    payload = _normalize_replay(source, _read_object(source))
    try:
        RecordedReplay.model_validate(payload)
    except ValidationError as exc:
        raise SkillLearningError(f"invalid replay file: {exc}") from exc
    destination = replay_dir(home) / f"{safe}.json"
    _write_json(destination, payload)
    return destination


def _safe_run_id(run_id: str) -> str:
    try:
        return check_run_id(run_id)
    except ValueError as exc:
        raise SkillLearningError(str(exc)) from exc


def _normalize_replay(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Accept ``{"passed": true}`` as well as ``{"outcome": "passed"}``."""
    if "outcome" in payload:
        return payload
    if "passed" not in payload:
        return payload
    passed = payload["passed"]
    if passed is True:
        outcome = ReplayOutcome.PASSED.value
    elif passed is False:
        outcome = ReplayOutcome.FAILED.value
    else:
        raise SkillLearningError(f"{path}: replay 'passed' must be true or false")
    normalized = dict(payload)
    normalized["outcome"] = outcome
    return normalized


def _read_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillLearningError(f"cannot read {path}: {exc}") from exc
    try:
        loaded: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SkillLearningError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(loaded, dict):
        raise SkillLearningError(f"{path}: JSON value must be an object")
    result: dict[str, Any] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise SkillLearningError(f"{path}: JSON keys must be strings")
        result[key] = value
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
