"""Visible memory writes with provenance.

``memory.mode`` is ``ask`` (prompt first), ``auto`` (write and say so), or
``off`` (do not read or write). Every saved record carries the run, the step,
and evidence ids when a ledger supplied them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swag_bot.interfaces import (
    ActionRequest,
    ApprovalPrompter,
    MemoryItem,
    MemoryStore,
    RiskLevel,
)

# Words that show up in almost every goal. They must not make an unrelated
# memory look relevant (a squares run injected into a later fizzbuzz run).
_STOP = frozenset(
    """
    a an the to of and or for with that this it is was were be been being
    write create save run execute check verify read file files print prints
    printed number numbers line lines output script code text txt csv py
    using from into in on at by one per each last its own not but you your
    goal step done met python python3
    """.split()
)
_TOKEN = re.compile(r"[a-z0-9_]+")
MEMORY_RELEVANCE_THRESHOLD = 0.2

MEMORY_MODES = frozenset({"ask", "auto", "off"})


@dataclass(frozen=True)
class MemoryNotice:
    """What to show the user after a memory decision."""

    text: str
    saved: bool


def normalize_memory_mode(mode: str) -> str:
    """Return ``ask``, ``auto``, or ``off``. Raise ``ValueError`` otherwise."""
    text = mode.strip().lower()
    if text not in MEMORY_MODES:
        raise ValueError("memory.mode must be ask, auto, or off")
    return text


def provenance_metadata(
    *,
    run_id: str,
    kind: str,
    goal: str,
    step_id: str = "",
    evidence_ids: Sequence[str] = (),
    workspace: str = "",
) -> dict[str, Any]:
    """Metadata stored with one memory so a later recall can say where it came from."""
    payload: dict[str, Any] = {
        "source": "swag",
        "kind": kind,
        "run_id": run_id,
        "goal": goal,
        "step_id": step_id,
        "evidence_ids": [str(item) for item in evidence_ids],
    }
    if workspace.strip():
        payload["workspace"] = workspace.strip()
    return payload


def memory_tokens(text: str) -> set[str]:
    """Distinctive words. Stopwords and one-letter tokens are dropped."""
    found: set[str] = set()
    for token in _TOKEN.findall(text.casefold()):
        if token in _STOP:
            continue
        if len(token) < 3 and not token.isdigit():
            continue
        found.add(token)
    return found


def memory_relevance(goal: str, item: MemoryItem, *, workspace: str = "") -> float:
    """Overlap of the goal's distinctive words with the memory and its goal.

    The score is the share of the goal's tokens that also appear in the
    memory. ``workspace`` raises the bar when the memory was saved somewhere
    else, and lowers it slightly for the same workspace.
    """
    del workspace
    goal_tokens = memory_tokens(goal)
    if not goal_tokens:
        return 0.0
    remembered = memory_tokens(item.content)
    remembered.update(memory_tokens(str(item.metadata.get("goal") or "")))
    if not remembered:
        return 0.0
    return len(goal_tokens & remembered) / len(goal_tokens)


def relevant_memories(
    items: Sequence[MemoryItem],
    goal: str,
    *,
    workspace: str = "",
    threshold: float = MEMORY_RELEVANCE_THRESHOLD,
    limit: int = 5,
) -> list[MemoryItem]:
    """Memories similar enough to ``goal`` to show the planner.

    A memory from a different workspace needs a stronger overlap. Memories
    with no shared distinctive words are dropped even when full-text search
    matched a stopword such as ``write``.
    """
    if limit <= 0:
        return []
    ranked: list[tuple[float, int, MemoryItem]] = []
    for index, item in enumerate(items):
        score = memory_relevance(goal, item)
        needed = _relevance_threshold(item, workspace, threshold)
        if score >= needed:
            ranked.append((score, index, item))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [item for _score, _index, item in ranked[:limit]]


def _relevance_threshold(item: MemoryItem, workspace: str, threshold: float) -> float:
    stored = str(item.metadata.get("workspace") or "").strip()
    current = workspace.strip()
    if not stored or not current:
        return threshold
    if _same_workspace(stored, current):
        return min(threshold, 0.15)
    return max(threshold, 0.5)


def _same_workspace(left: str, right: str) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return left == right


def label_memory(item: MemoryItem) -> str:
    """One line of content plus whatever provenance the record actually has.

    A run summary is stored in full, but recall shows the goal and provenance
    only. Pasting the saved ``# Summary`` record back into the next plan
    repeated that heading.
    """
    meta = item.metadata
    bits: list[str] = []
    kind = str(meta.get("kind") or "")
    run_id = str(meta.get("run_id") or "")
    step_id = str(meta.get("step_id") or "")
    if kind:
        bits.append(kind)
    if run_id:
        bits.append(f"run {run_id}")
    if step_id:
        bits.append(f"step {step_id}")
    if "evidence_ids" in meta:
        evidence = meta.get("evidence_ids") or []
        if isinstance(evidence, list) and evidence:
            bits.append("evidence " + ", ".join(str(entry) for entry in evidence))
        else:
            bits.append("evidence none")
    if kind == "run-summary":
        body = f"run summary for {str(meta.get('goal') or 'the goal')}"
    else:
        body = " ".join(item.content.split())
        if len(body) > 240:
            body = body[:237] + "..."
    if not bits:
        return f"{body} (no provenance)"
    return f"{body} ({', '.join(bits)})"


def recall_lines(items: Sequence[MemoryItem]) -> list[str]:
    """Terminal lines for memories that will be shown to the planner."""
    return [f"recalled: {label_memory(item)}" for item in items]


def remembered_text(item: MemoryItem) -> str:
    """Terminal and summary line for a write that succeeded.

    A run summary is stored in full, but the visible line stays short so the
    summary file does not repeat its own ``# Summary`` heading.
    """
    return f"remembered: {label_memory(item)}"


def commit_memory(
    store: MemoryStore,
    content: str,
    *,
    mode: str,
    prompter: ApprovalPrompter | None,
    metadata: Mapping[str, Any],
) -> MemoryNotice | None:
    """Save ``content`` according to ``mode``.

    ``off`` returns None so the caller can stay quiet after one run-level
    notice. ``ask`` prompts. A store error is reported and does not raise.
    """
    normalized = normalize_memory_mode(mode)
    if normalized == "off" or not content.strip():
        return None
    if normalized == "ask":
        if prompter is None:
            return MemoryNotice("memory not saved (no prompter)", saved=False)
        action = ActionRequest(
            kind="memory",
            summary=f"Save memory: {_clip(content, 160)}",
            risk=RiskLevel.WRITE,
            arguments={
                "kind": str(metadata.get("kind", "")),
                "run_id": str(metadata.get("run_id", "")),
                "step_id": str(metadata.get("step_id", "")),
            },
        )
        try:
            allowed = bool(prompter.prompt(action))
        except Exception:
            return MemoryNotice("memory not saved (prompt failed)", saved=False)
        if not allowed:
            return MemoryNotice("memory not saved (declined)", saved=False)
    try:
        item = store.add(content, metadata=dict(metadata))
    except Exception:
        return MemoryNotice("memory write failed", saved=False)
    return MemoryNotice(remembered_text(item), saved=True)


def append_remembered(summary: str, line: str) -> str:
    """Add one ``remembered:`` bullet under ``## Memory``."""
    bullet = f"- {line}"
    if "## Memory" in summary:
        return summary.rstrip() + "\n" + bullet + "\n"
    return summary.rstrip() + "\n\n## Memory\n\n" + bullet + "\n"


def _clip(text: str, limit: int) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."
