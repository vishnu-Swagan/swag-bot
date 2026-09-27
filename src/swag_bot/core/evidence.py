"""Per-run evidence ledger.

Tool results and acceptance checks are stored here, with stdout, stderr, and
file bodies in blob files addressed by SHA-256. ``run.jsonl`` is the canonical
log for one run. ``$SWAG_HOME/actions.jsonl`` stays an index of action rows so
``swag safety log`` and the run agree.

The shape is the Evidence Contract (``docs/spec/evidence-contract.md``).
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Sequence
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from swag_bot.core.redact import redact, redact_known
from swag_bot.interfaces import (
    EVIDENCE_CONTRACT_SPEC,
    EVIDENCE_CONTRACT_VERSION,
    ActionLogEntry,
    CheckResult,
    Evidence,
    RunRecord,
)

# Attempt number for the step currently executing. The loop sets this so a
# retry is judged on its own tool results, not on an earlier failed attempt.
current_attempt: ContextVar[int] = ContextVar("swag_evidence_attempt", default=1)

# Full bodies are stored, up to this many characters, instead of the old
# 2,000-character action-log clip. Past the cap the blob is marked truncated.
BLOB_CHAR_LIMIT = 2_000_000
_PREVIEW_LIMIT = 400

_SHELL_HEAD = re.compile(r"^exit_code=(-?\d+) timed_out=(true|false)$")
_STDERR_MARK = "\nstderr:\n"


def parse_shell_outcome(outcome: str) -> tuple[int, bool, str, str] | None:
    """Parse the ``run_shell`` tool text into exit code, timeout, stdout, stderr.

    Returns None when ``outcome`` is not that format. The split is on the last
    ``stderr:`` marker, which matches how ``core/tools.py`` formats the result.
    """
    first, sep, rest = outcome.partition("\n")
    if not sep:
        return None
    match = _SHELL_HEAD.match(first)
    if match is None or not rest.startswith("stdout:\n"):
        return None
    body = rest[len("stdout:\n") :]
    if _STDERR_MARK not in body:
        return None
    stdout, stderr = body.rsplit(_STDERR_MARK, 1)
    return int(match.group(1)), match.group(2) == "true", stdout, stderr


def sha256_text(text: str) -> str:
    """Hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EvidenceLedger:
    """Append-only evidence, check results, and actions for one run."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self.run_id = ""
        self.goal = ""
        self._events: list[RunRecord] = []
        self._blobs: dict[str, str] = {}
        self._lock = threading.Lock()

    def set_run(self, run_id: str, goal: str) -> None:
        """Remember the plan id written into the ``run.jsonl`` header."""
        with self._lock:
            self.run_id = run_id
            self.goal = goal

    def record_tool(
        self,
        *,
        step_id: str,
        tool: str,
        arguments: dict[str, Any],
        outcome: str,
        approved: bool,
        duration_ms: int | None = None,
    ) -> Evidence:
        """Store one tool result. Secrets are redacted before the bytes are hashed."""
        redacted_args = redact(arguments)
        if not isinstance(redacted_args, dict):
            redacted_args = {}
        cleaned = redact_known(outcome, arguments, redacted_args)
        exit_code: int | None = None
        stdout = ""
        stderr = ""
        content = ""
        path = _tool_path(tool, arguments)
        parsed = parse_shell_outcome(cleaned) if tool == "run_shell" else None
        timed_out = False
        if parsed is not None:
            exit_code, timed_out, stdout, stderr = parsed
        elif tool == "write_file":
            raw_content = arguments.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content)
            content = redact_known(content, arguments, redacted_args)
        elif tool == "read_file" and not cleaned.startswith("error:"):
            content = cleaned
        ok = _tool_ok(cleaned, approved=approved, exit_code=exit_code, timed_out=timed_out)
        detail = _tool_detail(tool, cleaned, exit_code=exit_code, timed_out=timed_out, ok=ok)
        evidence = Evidence(
            kind="tool",
            step_id=step_id,
            attempt=current_attempt.get(),
            tool=tool,
            summary=_summary(tool, path, arguments),
            exit_code=exit_code,
            path=path,
            ok=ok,
            detail=detail,
            preview=_preview(detail, stdout, stderr, content),
            duration_ms=duration_ms,
        )
        self._attach_bodies(evidence, stdout=stdout, stderr=stderr, content=content)
        self._append(RunRecord(record="evidence", evidence=evidence))
        return evidence

    def record_observation(
        self,
        *,
        step_id: str,
        kind: str,
        summary: str,
        ok: bool,
        detail: str,
        exit_code: int | None = None,
        path: str | None = None,
        stdout: str = "",
        stderr: str = "",
        content: str = "",
        tool: str | None = None,
    ) -> Evidence:
        """Store a check result or any other harness observation."""
        evidence = Evidence(
            kind=kind,
            step_id=step_id,
            attempt=current_attempt.get(),
            tool=tool,
            summary=summary,
            exit_code=exit_code,
            path=path,
            ok=ok,
            detail=detail,
            preview=_preview(detail, stdout, stderr, content),
        )
        self._attach_bodies(evidence, stdout=stdout, stderr=stderr, content=content)
        self._append(RunRecord(record="evidence", evidence=evidence))
        return evidence

    def add_action(self, entry: ActionLogEntry) -> None:
        """Copy one action row into the per-run log."""
        self._append(RunRecord(record="action", action=entry))

    def add_check_result(self, result: CheckResult) -> None:
        """Copy one check result into the per-run log."""
        self._append(RunRecord(record="check", check=result))

    def for_step(self, step_id: str, *, attempt: int | None = None) -> list[Evidence]:
        """Evidence for ``step_id``. ``attempt`` limits the list to one try."""
        with self._lock:
            found: list[Evidence] = []
            for event in self._events:
                item = event.evidence
                if item is None or item.step_id != step_id:
                    continue
                if attempt is not None and item.attempt != attempt:
                    continue
                found.append(item)
            return list(found)

    def excerpt(self, step_id: str, *, attempt: int | None = None, limit: int = 12) -> str:
        """Text the verifier may cite. This is ledger data, not the model's claim."""
        rows = self.for_step(step_id, attempt=attempt)
        if not rows:
            return "(no tool or check evidence for this attempt)"
        lines: list[str] = []
        for item in rows[-limit:]:
            bits = [f"id={item.id}", f"kind={item.kind}", f"ok={item.ok}"]
            if item.tool:
                bits.append(f"tool={item.tool}")
            if item.exit_code is not None:
                bits.append(f"exit_code={item.exit_code}")
            if item.path:
                bits.append(f"path={item.path}")
            if item.stdout_sha256:
                bits.append(f"stdout_sha256={item.stdout_sha256}")
            if item.content_sha256:
                bits.append(f"content_sha256={item.content_sha256}")
            lines.append("- " + " ".join(bits))
            if item.detail:
                lines.append(f"  detail: {item.detail}")
            if item.preview and item.preview != item.detail:
                lines.append(f"  preview: {item.preview}")
        return "\n".join(lines)

    def dump(self, directory: Path) -> Path:
        """Write blobs (if they were not written yet) and ``run.jsonl``."""
        directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            blobs = dict(self._blobs)
            run_id = self.run_id
            goal = self.goal
            events = list(self._events)
        for relative, text in blobs.items():
            target = directory / relative
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        header = RunRecord(
            record="header",
            version=EVIDENCE_CONTRACT_VERSION,
            spec=EVIDENCE_CONTRACT_SPEC,
            run_id=run_id or None,
            goal=goal or None,
        )
        lines = [header.model_dump_json(exclude_none=True)]
        lines.extend(event.model_dump_json(exclude_none=True) for event in events)
        path = directory / "run.jsonl"
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        return path

    def _append(self, event: RunRecord) -> None:
        with self._lock:
            self._events.append(event)

    def _attach_bodies(
        self,
        evidence: Evidence,
        *,
        stdout: str,
        stderr: str,
        content: str,
    ) -> None:
        truncated = False
        if stdout:
            blob, digest, cut = self._store(evidence.id, "stdout", stdout)
            evidence.stdout = stdout[:BLOB_CHAR_LIMIT]
            evidence.stdout_blob = blob
            evidence.stdout_sha256 = digest
            truncated = truncated or cut
        if stderr:
            blob, digest, cut = self._store(evidence.id, "stderr", stderr)
            evidence.stderr = stderr[:BLOB_CHAR_LIMIT]
            evidence.stderr_blob = blob
            evidence.stderr_sha256 = digest
            truncated = truncated or cut
        if content:
            blob, digest, cut = self._store(evidence.id, "content", content)
            evidence.content = content[:BLOB_CHAR_LIMIT]
            evidence.content_blob = blob
            evidence.content_sha256 = digest
            truncated = truncated or cut
        evidence.truncated = truncated

    def _store(self, evidence_id: str, suffix: str, text: str) -> tuple[str, str, bool]:
        truncated = False
        stored = text
        if len(stored) > BLOB_CHAR_LIMIT:
            stored = stored[:BLOB_CHAR_LIMIT]
            truncated = True
        relative = f"evidence/{evidence_id}.{suffix}"
        digest = sha256_text(stored)
        with self._lock:
            self._blobs[relative] = stored
            directory = self.directory
        if directory is not None:
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(stored, encoding="utf-8")
        return relative, digest, truncated


def ground_claim(
    *,
    claimed_pass: bool,
    reason: str,
    replan: bool,
    cited: Sequence[str],
    check_results: Sequence[CheckResult],
    evidence: Sequence[Evidence],
) -> tuple[bool, bool, bool, str, tuple[str, ...]]:
    """Decide whether a model's pass is allowed to count.

    Returns ``(passed, unverified, replan, reason, evidence_ids)``.

    Passing checks are enough: their evidence ids are attached even when the
    model forgets to cite them. A pass with no successful tool evidence and no
    passing check becomes unverified. A failed tool, with no passing check,
    is a failure even if the model says the step worked.
    """
    known = {item.id: item for item in evidence}
    if not claimed_pass:
        ids = _unique(
            [item for item in cited if item in known]
            + [item for result in check_results for item in result.evidence_ids]
        )
        text = reason.strip() or "the check failed"
        return False, False, replan, text, tuple(ids)

    passing_checks = [result for result in check_results if result.passed]
    check_ids = [item for result in passing_checks for item in result.evidence_ids]
    cited_ok = [item for item in cited if _supports_pass(item, known, check_ids)]
    if passing_checks and check_ids:
        text = reason.strip() or "acceptance checks passed"
        return True, False, False, text, tuple(_unique(cited_ok + check_ids))

    failed_tools = [item for item in evidence if item.kind == "tool" and item.ok is False]
    if failed_tools:
        failed_ids = tuple(item.id for item in failed_tools)
        details = "; ".join(_cite(item) for item in failed_tools)
        return (
            False,
            False,
            False,
            f"tool evidence contradicts a pass: {details}",
            failed_ids,
        )

    if cited_ok:
        text = reason.strip() or "passed"
        return True, False, False, text, tuple(_unique(cited_ok))

    successful = [item.id for item in evidence if item.kind == "tool" and item.ok is True]
    if successful:
        text = reason.strip() or "passed"
        return True, False, False, text, tuple(successful)

    return (
        False,
        True,
        False,
        "no evidence was cited; the step is unverified",
        (),
    )


def _supports_pass(evidence_id: str, known: dict[str, Evidence], check_ids: Sequence[str]) -> bool:
    if evidence_id in check_ids:
        return True
    item = known.get(evidence_id)
    return item is not None and item.ok is not False


def _cite(item: Evidence) -> str:
    if item.exit_code is not None:
        return f"{item.summary or item.tool or item.kind} exit_code={item.exit_code} ({item.id})"
    return f"{item.detail or item.summary or item.kind} ({item.id})"


def _unique(ids: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for item in ids:
        if item and item not in seen:
            seen.append(item)
    return seen


def _tool_ok(outcome: str, *, approved: bool, exit_code: int | None, timed_out: bool) -> bool:
    if not approved or timed_out:
        return False
    if outcome.startswith(("error:", "unknown tool")) or outcome in {"denied", "Action denied."}:
        return False
    if exit_code is not None and exit_code != 0:
        return False
    return True


def _tool_detail(
    tool: str,
    outcome: str,
    *,
    exit_code: int | None,
    timed_out: bool,
    ok: bool,
) -> str:
    if not ok and outcome in {"denied", "Action denied."}:
        return f"{tool} was denied"
    if outcome.startswith("unknown tool"):
        return outcome
    if outcome.startswith("error:"):
        return outcome
    if exit_code is not None:
        state = "timed out" if timed_out else f"exit_code={exit_code}"
        return f"{tool} {state}"
    if outcome.startswith("wrote "):
        return outcome
    return _preview(outcome) or tool


def _tool_path(tool: str, arguments: dict[str, Any]) -> str | None:
    if tool in {"read_file", "write_file"}:
        path = arguments.get("path")
        return str(path) if path else None
    if tool == "run_shell":
        command = arguments.get("command")
        return str(command) if command else None
    return None


def _summary(tool: str, path: str | None, arguments: dict[str, Any]) -> str:
    if path:
        return f"{tool} {path}"
    if arguments:
        return tool
    return tool


def _preview(*parts: str, limit: int = _PREVIEW_LIMIT) -> str:
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
