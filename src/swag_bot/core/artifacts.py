"""Files ``swag run`` leaves in the output directory.

User files stay in the output directory. Swag Bot's own files live in
``<output>/.swag/`` so a task that writes ``fizzbuzz.py`` does not sit next
to ``plan.json``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from swag_bot.core.evidence import EvidenceLedger
from swag_bot.interfaces import ActionLogEntry, TaskPlan

INTERNAL_DIR = ".swag"
_SUMMARY_NAME = "summary.md"


def internal_dir(directory: Path) -> Path:
    """``<output>/.swag``, where plan, logs, and evidence are stored."""
    return directory / INTERNAL_DIR


def artifact_file(directory: Path, name: str) -> Path:
    """Path of one run file, preferring ``.swag`` and still reading the old layout.

    ``summary.md`` stays in the output directory. Other internal names
    (``plan.json``, ``action-log.jsonl``, ``run.jsonl``) are under ``.swag``.
    """
    if name == _SUMMARY_NAME:
        return directory / _SUMMARY_NAME
    modern = internal_dir(directory) / name
    legacy = directory / name
    if modern.is_file() or not legacy.is_file():
        return modern
    return legacy


def find_run_log(directory: Path) -> Path | None:
    """``run.jsonl`` under ``.swag``, or the older top-level file when present."""
    for candidate in (internal_dir(directory) / "run.jsonl", directory / "run.jsonl"):
        if candidate.is_file():
            return candidate
    return None


def default_output_dir(now: datetime | None = None) -> Path:
    """``./swag-output/<local timestamp>``. A suffix is added if that directory exists."""
    if now is None:
        moment = datetime.now().astimezone()
    elif now.tzinfo is not None:
        moment = now.astimezone()
    else:
        moment = now
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
    """Write the summary beside user files, and internal logs under ``.swag``.

    ``summary.md`` stays in ``directory``. ``plan.json``, ``action-log.jsonl``,
    and ``run.jsonl`` (plus evidence blobs) are written to ``directory/.swag``.
    When ``ledger`` is omitted, ``run.jsonl`` is not written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    hidden = internal_dir(directory)
    hidden.mkdir(parents=True, exist_ok=True)
    (hidden / "plan.json").write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    lines = "".join(entry.model_dump_json() + "\n" for entry in entries)
    (hidden / "action-log.jsonl").write_text(lines, encoding="utf-8")
    text = summary if summary.endswith("\n") else summary + "\n"
    (directory / _SUMMARY_NAME).write_text(text, encoding="utf-8")
    if ledger is not None:
        ledger.dump(hidden)
