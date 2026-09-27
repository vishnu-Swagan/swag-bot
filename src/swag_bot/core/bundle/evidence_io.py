"""Include a per-run evidence ledger in the bundle.

When ``<output-dir>/run.jsonl`` exists, it is copied verbatim. That is the
file written by the evidence ledger (``docs/spec/evidence-contract.md``).
When it does not exist yet, the bundle writes a compatible ``run.jsonl``
from the tool calls and actions this recorder saw.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from swag_bot.core.bundle.files import sha256_text
from swag_bot.core.bundle.redact import redact_text, redact_value
from swag_bot.core.bundle.spec import (
    BLOB_CHAR_LIMIT,
    EVIDENCE_SPEC,
    EVIDENCE_VERSION,
    PREVIEW_LIMIT,
)


def include_evidence(
    destination: Path,
    output_dir: Path | None,
    *,
    run_id: str,
    goal: str,
    tools: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> str:
    """Write ``evidence/run.jsonl``. Return ``run.jsonl`` or ``synthesized``."""
    evidence_dir = destination / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    source = None if output_dir is None else output_dir / "run.jsonl"
    target = evidence_dir / "run.jsonl"
    if source is not None and source.is_file() and source.resolve() != target.resolve():
        copy_redacted_ledger(source, target)
        return "run.jsonl"
    lines = _synthesize(evidence_dir, run_id=run_id, goal=goal, tools=tools, actions=actions)
    target.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return "synthesized"


def copy_redacted_ledger(source: Path, target: Path) -> None:
    """Copy a ledger and strip secrets. The bundle is meant to be shared."""
    lines = [redact_text(line) for line in source.read_text(encoding="utf-8").splitlines()]
    text = "\n".join(lines)
    if text:
        text += "\n"
    target.write_text(text, encoding="utf-8")


def _synthesize(
    evidence_dir: Path,
    *,
    run_id: str,
    goal: str,
    tools: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> list[str]:
    header = {
        "record": "header",
        "spec": EVIDENCE_SPEC,
        "version": EVIDENCE_VERSION,
        "run_id": run_id or None,
        "goal": goal or None,
    }
    lines = [_dumps(header)]
    for call in tools:
        evidence = _tool_evidence(evidence_dir, call)
        lines.append(_dumps({"record": "evidence", "evidence": evidence}))
    for action in actions:
        lines.append(_dumps({"record": "action", "action": redact_value(action)}))
    return lines


def _tool_evidence(evidence_dir: Path, call: dict[str, Any]) -> dict[str, Any]:
    outcome = call.get("result")
    text = outcome if isinstance(outcome, str) else ""
    text = redact_text(text)
    truncated = len(text) > BLOB_CHAR_LIMIT
    if truncated:
        text = text[:BLOB_CHAR_LIMIT]
    tool = str(call.get("name") or "")
    arguments = call.get("arguments")
    args = arguments if isinstance(arguments, dict) else {}
    path = _path_of(tool, args)
    exit_code = _exit_code(text) if tool == "run_shell" else None
    denied = text.strip() in {"denied", "Action denied."} or text.startswith("error:")
    failed_tool = text.startswith("unknown tool:")
    ok = not denied and not failed_tool and (exit_code is None or exit_code == 0)
    evidence_id = f"ev-{uuid4().hex[:12]}"
    preview = text[:PREVIEW_LIMIT]
    evidence: dict[str, Any] = {
        "id": evidence_id,
        "kind": "tool",
        "step_id": call.get("step_id"),
        "attempt": call.get("attempt"),
        "tool": tool or None,
        "summary": _summary(tool, path),
        "exit_code": exit_code,
        "path": path,
        "ok": ok,
        "detail": preview.splitlines()[0] if preview else "",
        "preview": preview,
        "truncated": truncated,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if text:
        digest = sha256_text(text)
        relative = f"evidence/{evidence_id}.content"
        blob = evidence_dir / f"{evidence_id}.content"
        blob.write_text(text, encoding="utf-8")
        evidence["content_sha256"] = digest
        evidence["content_blob"] = relative
    return evidence


def _path_of(tool: str, arguments: dict[str, Any]) -> str | None:
    if tool in {"read_file", "write_file"}:
        path = arguments.get("path")
        return str(path) if path else None
    if tool == "run_shell":
        command = arguments.get("command")
        return str(command) if command else None
    return None


def _summary(tool: str, path: str | None) -> str:
    if path:
        return f"{tool} {path}"
    return tool or "tool"


def _exit_code(outcome: str) -> int | None:
    first = outcome.split("\n", 1)[0]
    if not first.startswith("exit_code="):
        return None
    token = first.split()[0]
    raw = token.split("=", 1)[1]
    try:
        return int(raw)
    except ValueError:
        return None


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str)
