"""Pass finished-step results and files to the steps that depend on them.

A later step used to start from its own instruction only. This module builds
a short manifest (observation, files that changed, evidence ids) and renders
it into the next step's prompt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_READ_LIMIT = 8000
_EXCERPT = 400
_FILE_CAP = 20
_SKIP_DIRS = frozenset({".git", "__pycache__", "bundle", "evidence"})
_SKIP_FILES = frozenset({"plan.json", "action-log.jsonl", "summary.md", "run.jsonl"})


@dataclass(frozen=True)
class StepManifest:
    """What a finished step hands to the steps that list it in ``depends_on``."""

    step_id: str
    title: str
    observation: str
    files: tuple[tuple[str, str], ...] = ()
    evidence_ids: tuple[str, ...] = ()


def snapshot_text_files(root: Path) -> dict[str, str]:
    """Relative path to a capped text snapshot of each regular file under ``root``."""
    found: dict[str, str] = {}
    if not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        parts = relative.split("/")
        if parts[0] in _SKIP_DIRS or (len(parts) == 1 and parts[0] in _SKIP_FILES):
            continue
        try:
            found[relative] = path.read_bytes()[:_READ_LIMIT].decode("utf-8", errors="replace")
        except OSError:
            continue
    return found


def changed_files(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    limit: int = _FILE_CAP,
) -> list[tuple[str, str]]:
    """Files created, edited, or removed between two snapshots.

    Each pair is ``(relative path, excerpt)``. Removals use the excerpt
    ``(deleted)``. At most ``limit`` paths are returned, in path order.
    """
    notes: list[tuple[str, str]] = []
    paths = sorted(set(before) | set(after))
    for path in paths:
        previous = before.get(path)
        current = after.get(path)
        if previous == current:
            continue
        if current is None:
            notes.append((path, "(deleted)"))
        else:
            notes.append((path, _excerpt(current)))
        if len(notes) >= limit:
            break
    return notes


def render_handoff(manifests: Sequence[StepManifest]) -> str:
    """Prompt text for dependency manifests. Empty when there is nothing to hand off."""
    if not manifests:
        return ""
    lines = ["Results from earlier steps this step depends on:"]
    for item in manifests:
        lines.append(f"- {item.step_id}: {item.title}")
        observation = _one_line(item.observation)
        if observation:
            lines.append(f"  observation: {observation}")
        if item.files:
            lines.append("  files:")
            for path, excerpt in item.files:
                lines.append(f"    - {path}: {_one_line(excerpt)}")
        else:
            lines.append("  files: (none)")
        if item.evidence_ids:
            lines.append("  evidence: " + ", ".join(item.evidence_ids))
        else:
            lines.append("  evidence: (none)")
    return "\n".join(lines)


def _excerpt(text: str) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= _EXCERPT:
        return flattened
    return flattened[: _EXCERPT - 3] + "..."


def _one_line(text: str, limit: int = 500) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."
