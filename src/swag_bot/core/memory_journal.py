"""Visible memory writes with provenance.

``memory.mode`` is ``ask`` (prompt first), ``auto`` (write and say so), or
``off`` (do not read or write). Every saved record carries the run, the step,
and evidence ids when a ledger supplied them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from swag_bot.interfaces import (
    ActionRequest,
    ApprovalPrompter,
    MemoryItem,
    MemoryStore,
    RiskLevel,
)

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
) -> dict[str, Any]:
    """Metadata stored with one memory so a later recall can say where it came from."""
    return {
        "source": "swag",
        "kind": kind,
        "run_id": run_id,
        "goal": goal,
        "step_id": step_id,
        "evidence_ids": [str(item) for item in evidence_ids],
    }


def label_memory(item: MemoryItem) -> str:
    """One line of content plus whatever provenance the record actually has."""
    body = " ".join(item.content.split())
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
    if str(item.metadata.get("kind") or "") == "run-summary":
        goal = str(item.metadata.get("goal") or "the goal")
        run_id = str(item.metadata.get("run_id") or "")
        where = f", run {run_id}" if run_id else ""
        evidence = "evidence none"
        raw = item.metadata.get("evidence_ids") or []
        if isinstance(raw, list) and raw:
            evidence = "evidence " + ", ".join(str(entry) for entry in raw)
        return f"remembered: run summary for {goal} (run-summary{where}, {evidence})"
    preview = label_memory(item)
    if len(preview) > 240:
        preview = preview[:237] + "..."
    return f"remembered: {preview}"


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
