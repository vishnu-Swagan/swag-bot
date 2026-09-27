"""Files ``swag run`` leaves in the output directory."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from swag_bot.core.evidence import EvidenceLedger
from swag_bot.interfaces import ActionLogEntry, TaskPlan


def default_output_dir(now: datetime | None = None) -> Path:
    """``./swag-output/<UTC timestamp>``. A suffix is added if that directory exists."""
    moment = now or datetime.now(UTC)
    stamp = moment.strftime("%Y%m%d-%H%M%S")
    path = Path("swag-output") / stamp
    if path.exists():
        path = Path("swag-output") / f"{stamp}-{uuid4().hex[:6]}"
    return path


def write_run_artifacts(
    directory: Path,
    plan: TaskPlan,
    entries: Sequence[ActionLogEntry],
    summary: str,
    ledger: EvidenceLedger | None = None,
) -> None:
    """Write ``plan.json``, ``action-log.jsonl``, ``summary.md``, and ``run.jsonl``.

    ``action-log.jsonl`` is the action subset. ``run.jsonl`` is the Evidence
    Contract log (header, evidence, actions, and check results). When
    ``ledger`` is omitted, ``run.jsonl`` is not written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plan.json").write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    lines = "".join(entry.model_dump_json() + "\n" for entry in entries)
    (directory / "action-log.jsonl").write_text(lines, encoding="utf-8")
    text = summary if summary.endswith("\n") else summary + "\n"
    (directory / "summary.md").write_text(text, encoding="utf-8")
    if ledger is not None:
        ledger.dump(directory)
