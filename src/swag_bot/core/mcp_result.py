"""Structured JSON returned by ``swag_run_task`` and the polled task tools.

A string summary wrapped as ``{"result": "..."}`` left the chat model with
nothing to quote, so it invented file contents. This payload names the
outcome, the goal checks, the output folder, and the files the goal asked for.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from swag_bot.core.artifacts import default_output_dir, write_run_artifacts
from swag_bot.core.goal_checks import filenames_in_goal
from swag_bot.interfaces import CheckResult, TaskPlan

_SMALL_TEXT_BYTES = 4096
_MAX_LISTED_FILES = 40
_SKIP_FILE_NAMES = frozenset({"summary.md", "plan.json", "action-log.jsonl", "run.jsonl"})
_FAILURE = frozenset({"not_met", "aborted"})


def result_json(payload: dict[str, Any]) -> str:
    """Serialize one task payload. Keys stay stable for the MCP client."""
    return json.dumps(payload)


def is_failure_status(status: object) -> bool:
    """True when the task did not meet the goal or stopped early."""
    return status in _FAILURE


def result_payload(
    goal: str,
    result: Any,
) -> dict[str, Any]:
    """Build the payload from an ``execute_goal`` result.

    ``result`` is typed loosely so this module does not import the CLI.
    It must have ``summary``, ``output_dir``, ``exit_code``, and ``goal_checks``.
    """
    output = result.output_dir
    checks = tuple(result.goal_checks)
    status = "met" if result.exit_code == 0 else "not_met"
    return _payload(
        status=status,
        summary=str(result.summary),
        output_dir=output if isinstance(output, Path) else None,
        checks=checks,
        goal=goal,
    )


def declined_result(goal: str) -> dict[str, Any]:
    """Stop a declined approval before the model runs, and write ``summary.md``."""
    summary = (
        "# Summary\n\n"
        "Goal not met.\n\n"
        "The user declined the MCP approval, so this task stopped before it ran.\n\n"
        f"Goal: {goal}\n\n"
        "## Result\n\n"
        "The user declined. This is not a success.\n"
    )
    destination = default_output_dir()
    plan = TaskPlan(goal=goal, steps=[])
    write_run_artifacts(destination, plan, [], summary)
    payload = _payload(
        status="not_met",
        summary=summary,
        output_dir=destination,
        checks=(),
        goal=goal,
    )
    payload["message"] = "The user declined the MCP approval. The task did not run."
    return payload


def not_ready_result(goal: str, reason: str) -> dict[str, Any]:
    """Fail a task that has no usable model, with the setup command in the text."""
    text = reason.strip() or "Swag Bot is not ready."
    if "`swag setup --auto`" not in text:
        text = f"{text} Run `swag setup --auto`."
    summary = (
        "# Summary\n\n"
        "Goal not met.\n\n"
        "Swag Bot did not start this task because setup is not finished.\n\n"
        f"{text}\n\n"
        f"Goal: {goal}\n\n"
        "## Result\n\n"
        "Setup is not ready. This is not a success.\n"
    )
    payload = _payload(status="aborted", summary=summary, output_dir=None, checks=(), goal=goal)
    payload["message"] = text
    return payload


def failure_result(goal: str, exc: BaseException) -> dict[str, Any]:
    """Structured abort after ``execute_goal`` raised.

    A declined approval that reached the loop is ``not_met``. Anything else
    is ``aborted``. The output folder is included when the run created one.
    """
    output = getattr(exc, "swag_output_dir", None)
    summary = getattr(exc, "swag_summary", "")
    checks = getattr(exc, "swag_goal_checks", ())
    if not isinstance(summary, str) or not summary.strip():
        summary = (
            "# Summary\n\n"
            "Goal not met.\n\n"
            "The run stopped before it finished.\n\n"
            f"{exc}\n\n"
            f"Goal: {goal}\n\n"
            "## Result\n\n"
            "The run did not finish. This is not a success.\n"
        )
    if not isinstance(checks, tuple):
        checks = tuple(checks) if isinstance(checks, Sequence) else ()
    typed = tuple(item for item in checks if isinstance(item, CheckResult))
    declined = "declined" in str(exc).lower() or "declined" in summary.lower()
    status = "not_met" if declined else "aborted"
    folder = output if isinstance(output, Path) else None
    payload = _payload(
        status=status, summary=summary, output_dir=folder, checks=typed, goal=goal
    )
    payload["message"] = str(exc)
    return payload


def list_output_files(output_dir: Path | None, goal: str) -> list[dict[str, Any]]:
    """Files the goal named, then other user files in the output folder.

    Internal run files (``summary.md``, ``.swag/``) are left out. Small UTF-8
    files include their text. Missing requested files are listed as not written
    so a chat model does not invent their contents.
    """
    requested = filenames_in_goal(goal)
    found: dict[str, Path] = {}
    root = output_dir.resolve() if output_dir is not None and output_dir.is_dir() else None
    if root is not None:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if not _inside(root, path):
                continue
            relative = path.relative_to(root)
            if _skipped(relative):
                continue
            found[relative.as_posix()] = path
            if len(found) >= _MAX_LISTED_FILES:
                break

    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for name in requested:
        matches = [rel for rel in found if rel == name or rel.endswith("/" + name)]
        if not matches:
            rows.append(
                {
                    "path": name,
                    "exists": False,
                    "size": None,
                    "content": None,
                    "note": "not written",
                }
            )
            continue
        for rel in matches:
            rows.append(_file_row(found[rel], rel))
            used.add(rel)
    for rel in sorted(found):
        if rel in used:
            continue
        rows.append(_file_row(found[rel], rel))
    return rows


def _payload(
    *,
    status: str,
    summary: str,
    output_dir: Path | None,
    checks: Sequence[CheckResult],
    goal: str,
) -> dict[str, Any]:
    folder = ""
    if output_dir is not None:
        folder = str(output_dir.resolve())
    return {
        "status": status,
        "goal_checks": [_check_row(item) for item in checks],
        "output_dir": folder,
        "files": list_output_files(output_dir, goal),
        "summary": summary,
    }


def _check_row(item: CheckResult) -> dict[str, Any]:
    return {
        "check_id": item.check_id,
        "passed": item.passed,
        "evidence_ids": list(item.evidence_ids),
        "detail": item.detail,
    }


def _file_row(path: Path, relative: str) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        return {
            "path": relative,
            "exists": False,
            "size": None,
            "content": None,
            "note": "not written",
        }
    content = _read_small_text(path, size)
    row: dict[str, Any] = {
        "path": relative,
        "exists": True,
        "size": size,
        "content": content,
    }
    if content is None:
        if size > _SMALL_TEXT_BYTES:
            row["note"] = f"file is larger than {_SMALL_TEXT_BYTES} bytes; content omitted"
        else:
            row["note"] = "content omitted"
    return row


def _read_small_text(path: Path, size: int) -> str | None:
    if size > _SMALL_TEXT_BYTES:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _skipped(relative: Path) -> bool:
    if relative.name in _SKIP_FILE_NAMES:
        return True
    return ".swag" in relative.parts


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True
