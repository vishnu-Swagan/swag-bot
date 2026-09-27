"""Quarantine and active-skill directories under ``$SWAG_HOME``.

Candidates live in ``skill-candidates/``. Promoted skills are copied to
``skills/``, which the existing standalone skill discovery already scans.
Quarantine is not on that path, so a candidate is not an active skill.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.gate import GateDecision
from swag_bot.learning.protocols import SkillProvenance
from swag_bot.learning.records import CandidateRecord, CandidateStatus


def quarantine_root(home: Path) -> Path:
    """Directory of candidate folders. Not scanned as active skills."""
    return home / "skill-candidates"


def active_skills_root(home: Path) -> Path:
    """``$SWAG_HOME/skills``, already discovered as standalone skills."""
    return home / "skills"


def candidate_dir(home: Path, candidate_id: str) -> Path:
    """One candidate folder. The id must be a single safe path segment."""
    _check_segment(candidate_id, label="candidate id")
    return quarantine_root(home) / candidate_id


def active_skill_dir(home: Path, skill_name: str) -> Path:
    """Directory of one promoted skill."""
    _check_segment(skill_name, label="skill name")
    return active_skills_root(home) / skill_name


def write_quarantine(home: Path, record: CandidateRecord, files: Mapping[str, str]) -> Path:
    """Write the review copy and then ``candidate.json``."""
    root = candidate_dir(home, record.id)
    skill_root = root / record.skill_name
    _check_segment(record.skill_name, label="skill name")
    _write_tree(skill_root, files)
    _write_model(root / "candidate.json", record)
    return root


def save_record(home: Path, record: CandidateRecord) -> None:
    """Update ``candidate.json`` without touching the skill body."""
    path = candidate_dir(home, record.id) / "candidate.json"
    if not path.is_file():
        raise SkillLearningError(f"no candidate {record.id}")
    _write_model(path, record)


def load_record(home: Path, candidate_id: str) -> CandidateRecord:
    """Load one candidate. Raise ``SkillLearningError`` if it is missing or broken."""
    path = candidate_dir(home, candidate_id) / "candidate.json"
    if not path.is_file():
        raise SkillLearningError(f"no candidate {candidate_id}")
    return _read_record(path)


def list_records(home: Path) -> list[CandidateRecord]:
    """Every candidate, oldest first. Dot-directories are skipped."""
    root = quarantine_root(home)
    if not root.is_dir():
        return []
    found: list[CandidateRecord] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        path = child / "candidate.json"
        if path.is_file():
            found.append(_read_record(path))
    found.sort(key=lambda item: (item.created_at, item.id))
    return found


def find_open_candidate(home: Path, run_id: str) -> CandidateRecord | None:
    """The promoted candidate for this run, else the newest quarantined one."""
    matches = [
        item
        for item in list_records(home)
        if item.run_id == run_id and item.status is not CandidateStatus.REJECTED
    ]
    promoted = [item for item in matches if item.status is CandidateStatus.PROMOTED]
    if promoted:
        return promoted[-1]
    quarantined = [item for item in matches if item.status is CandidateStatus.QUARANTINED]
    if not quarantined:
        return None
    return quarantined[-1]


def skill_dir_of(home: Path, record: CandidateRecord) -> Path:
    """Review copy of the skill inside the candidate folder."""
    return candidate_dir(home, record.id) / record.skill_name


def publish_skill(
    home: Path,
    skill_name: str,
    files: Mapping[str, str],
    *,
    decision: GateDecision,
    provenance: SkillProvenance,
) -> Path:
    """Copy a skill into the active directory. A closed gate never writes it."""
    if not decision.allowed:
        raise SkillLearningError(
            "refusing to publish a skill the gate did not allow: " + decision.explain()
        )
    destination = active_skill_dir(home, skill_name)
    if destination.is_symlink():
        raise SkillLearningError(f"refusing to replace a symlinked skill {skill_name}")
    if destination.exists():
        existing = read_provenance(destination)
        if (
            existing is not None
            and existing.candidate_id == provenance.candidate_id
            and existing.source_run == provenance.source_run
        ):
            return destination
        raise SkillLearningError(f"active skill {skill_name} already exists")
    staging_root = quarantine_root(home) / ".staging"
    staging = staging_root / skill_name
    if staging.exists() or staging.is_symlink():
        _remove_tree(staging)
    try:
        _write_tree(staging, files)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(destination)
    except Exception:
        if staging.exists() or staging.is_symlink():
            _remove_tree(staging)
        raise
    return destination


def remove_active_skill(home: Path, skill_name: str) -> bool:
    """Delete one active skill directory. Return True if it existed.

    Symlinks are refused so a skill name cannot point the delete outside
    ``$SWAG_HOME/skills``.
    """
    root = active_skills_root(home)
    raw = active_skill_dir(home, skill_name)
    if raw.is_symlink():
        raise SkillLearningError(f"refusing to delete a symlinked skill {skill_name}")
    if not raw.exists():
        return False
    resolved = raw.resolve()
    base = root.resolve()
    if resolved != base and base not in resolved.parents:
        raise SkillLearningError(f"refusing to delete {skill_name} outside the skills directory")
    shutil.rmtree(resolved)
    return True


def read_provenance(skill_directory: Path) -> SkillProvenance | None:
    """Provenance written at promotion, or None when the file is absent."""
    path = skill_directory / "references" / "provenance.json"
    if not path.is_file():
        return None
    try:
        return SkillProvenance.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise SkillLearningError(f"{path}: invalid provenance ({exc})") from exc


def _write_model(path: Path, record: CandidateRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _read_record(path: Path) -> CandidateRecord:
    try:
        return CandidateRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise SkillLearningError(f"{path}: invalid candidate ({exc})") from exc


def _write_tree(root: Path, files: Mapping[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    base = root.resolve()
    for relative, text in files.items():
        path = _relative(base, root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _relative(base: Path, root: Path, relative: str) -> Path:
    raw = Path(relative)
    if relative.startswith(("/", "\\")) or raw.is_absolute() or ".." in raw.parts or not raw.parts:
        raise SkillLearningError(f"skill path escapes the skill directory: {relative}")
    candidate = (root / raw).resolve()
    if candidate != base and base not in candidate.parents:
        raise SkillLearningError(f"skill path escapes the skill directory: {relative}")
    return candidate


def _check_segment(value: str, *, label: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise SkillLearningError(f"invalid {label}: {value!r}")


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.exists():
        shutil.rmtree(path)
