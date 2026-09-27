"""Acceptance checks the harness runs itself.

The planner attaches ``Step.checks``. This module also derives checks from
success criteria when the model omits the array. Checks run through the
sandbox (and the permission policy for commands). They do not trust the
executor's description of what happened.

See ``docs/spec/evidence-contract.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from swag_bot.core.evidence import EvidenceLedger, current_attempt
from swag_bot.core.executor import _initial_risk, _policy_decision
from swag_bot.core.parsing import PlanParseError
from swag_bot.errors import SandboxError
from swag_bot.interfaces import (
    ActionKind,
    ActionLogEntry,
    ActionRequest,
    ApprovalPrompter,
    AutonomyLevel,
    Check,
    CheckResult,
    PermissionPolicy,
    RiskLevel,
    Sandbox,
    Step,
    resolve_sandbox_path,
)

# A check command that forgets a timeout cannot hang the run forever.
DEFAULT_CHECK_TIMEOUT = 60.0

OnAction = Callable[[ActionLogEntry], None]

_KIND_ALIAS = {
    "exists": "file_exists",
    "file_exists": "file_exists",
    "contains": "file_contains",
    "file_contains": "file_contains",
    "absent": "file_absent",
    "file_absent": "file_absent",
    "cmd": "command",
    "command": "command",
    "exit": "exit_code",
    "exit_code": "exit_code",
    "json": "json_schema",
    "json_schema": "json_schema",
    "stdout": "stdout",
    "output": "stdout",
}

_SHORTHAND = re.compile(
    r"(?im)^[ \t]*(?:[-*][ \t]*)?(?:check:[ \t]*)?"
    r"(file_exists|file_contains|file_absent|contains|command|cmd|exit_code|exit|json_schema|json)"
    r"[ \t]*:[ \t]*(.+?)\s*$"
)
_EXITS = re.compile(r"\s+exits\s+(-?\d+)\s*$", re.IGNORECASE)
_PATH_TEXT = re.compile(
    r"^(?P<path>\S+)\s+(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<bare>.+))$"
)
_NL_CONTAINS = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)"
    r"\s+contains\s+(?:\"(?P<dq>[^\"]+)\"|'(?P<sq>[^']+)'|(?P<bare>\S+))",
    re.IGNORECASE,
)
_NL_EXISTS = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)\s+exists\b",
    re.IGNORECASE,
)


def canonical_kind(kind: str) -> str:
    """Map a spec alias (``cmd``, ``contains``, ...) to the canonical kind."""
    return _KIND_ALIAS.get(kind.strip(), kind.strip())


def describe_check(check: Check) -> str:
    """One line a prompt can show for ``check``."""
    kind = canonical_kind(check.kind)
    if kind in {"file_exists", "file_absent", "json_schema"}:
        return f"{kind}: {check.path or '(no path)'}"
    if kind == "file_contains":
        return f"{kind}: {check.path or '(no path)'} contains {check.contains or ''}".rstrip()
    if kind == "command":
        expected = 0 if check.expected_exit is None else check.expected_exit
        return f"{kind}: {check.command or '(no command)'} exits {expected}"
    if kind == "exit_code":
        expected = 0 if check.expected_exit is None else check.expected_exit
        return f"{kind}: {expected}"
    if kind == "stdout":
        bits: list[str] = []
        if check.stdout_last_line:
            bits.append(f"last line {check.stdout_last_line}")
        if check.stdout_line_count is not None:
            bits.append(f"{check.stdout_line_count} lines")
        return "stdout: " + (", ".join(bits) if bits else (check.description or "output"))
    return check.description or kind


def checks_for_step(item: dict[str, Any], instruction: str) -> list[Check]:
    """Checks from a planner object, or derived from ``instruction``.

    An explicit ``checks`` key is authoritative, including an empty list.
    A missing key means "derive what you can from the success criteria".
    """
    if "checks" in item or "acceptance_checks" in item:
        raw = item["checks"] if "checks" in item else item.get("acceptance_checks")
        return parse_check_list(raw)
    return derive_checks(instruction)


def parse_check_list(raw: Any) -> list[Check]:
    """Validate a model's ``checks`` value. Raises ``PlanParseError`` when it is unusable."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise PlanParseError("checks must be a list")
    checks: list[Check] = []
    for index, entry in enumerate(raw, start=1):
        checks.append(_check_from_obj(entry, index))
    return checks


def derive_checks(text: str) -> list[Check]:
    """Pull machine checks out of success criteria.

    Recognizes the spec's shorthand (``file_exists: report.md``,
    ``cmd: pytest -q exits 0``) and two plain phrases: ``report.md exists``
    and ``report.md contains "Total"``.
    """
    found: list[Check] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(check: Check) -> None:
        key = (
            canonical_kind(check.kind),
            check.path or "",
            check.command or "",
            check.contains or "",
            "" if check.expected_exit is None else str(check.expected_exit),
        )
        if key in seen:
            return
        seen.add(key)
        check.id = check.id or f"chk-{len(found) + 1}"
        found.append(check)

    for match in _SHORTHAND.finditer(text or ""):
        built = _from_shorthand(match.group(1), match.group(2).strip())
        if built is not None:
            add(built)
    for match in _NL_EXISTS.finditer(text or ""):
        add(Check(kind="file_exists", path=match.group("path"), description=match.group(0)))
    for match in _NL_CONTAINS.finditer(text or ""):
        snippet = match.group("dq") or match.group("sq") or match.group("bare") or ""
        add(
            Check(
                kind="file_contains",
                path=match.group("path"),
                contains=snippet,
                description=match.group(0),
            )
        )
    return found


def _latest_output(items: list[Any]) -> Any:
    """Last command evidence that captured stdout, else the last exit code.

    A later check row can store an exit code and an empty stdout. That row
    must not hide the command output a line-count check still needs.
    """
    chosen = None
    with_stdout = None
    for item in items:
        if item.stdout or item.exit_code is not None:
            chosen = item
        if item.stdout:
            with_stdout = item
    return with_stdout if with_stdout is not None else chosen


class CheckRunner:
    """Run a step's checks through the sandbox and record the evidence."""

    def __init__(
        self,
        *,
        sandbox: Sandbox,
        ledger: EvidenceLedger,
        policy: PermissionPolicy | None = None,
        prompter: ApprovalPrompter | None = None,
        on_action: OnAction | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.ledger = ledger
        self.policy = policy
        self.prompter = prompter
        self.on_action = on_action

    def run(self, step: Step) -> list[CheckResult]:
        """Run every check. An empty list means the step has no machine checks."""
        results: list[CheckResult] = []
        for index, check in enumerate(step.checks, start=1):
            if not check.id.strip():
                check.id = f"chk-{index}"
            result = self._run_one(step, check)
            self.ledger.add_check_result(result)
            results.append(result)
        return results

    def _run_one(self, step: Step, check: Check) -> CheckResult:
        kind = canonical_kind(check.kind)
        try:
            if kind == "file_exists":
                return self._file_exists(step, check, absent=False)
            if kind == "file_absent":
                return self._file_exists(step, check, absent=True)
            if kind == "file_contains":
                return self._file_contains(step, check)
            if kind == "command":
                return self._command(step, check)
            if kind == "exit_code":
                return self._exit_code(step, check)
            if kind == "stdout":
                return self._stdout(step, check)
            if kind == "json_schema":
                return self._json_schema(step, check)
        except (SandboxError, OSError, UnicodeError) as exc:
            return self._finish(
                step,
                check,
                ok=False,
                detail=f"{check.id}: {exc}",
                summary=describe_check(check),
            )
        return self._finish(
            step,
            check,
            ok=False,
            detail=f"{check.id}: unsupported check kind {check.kind!r}",
            summary=describe_check(check),
        )

    def _file_exists(self, step: Step, check: Check, *, absent: bool) -> CheckResult:
        path = (check.path or "").strip()
        if not path:
            return self._finish(step, check, ok=False, detail=f"{check.id}: path is required")
        action = _read_action(check, path)
        allowed, approver, action = self._authorize(action)
        if not allowed:
            return self._denied(step, check, action, approver)
        try:
            target = resolve_sandbox_path(self.sandbox.workdir, path)
        except SandboxError as exc:
            return self._logged(
                step, check, action, approver, ok=False, detail=f"{check.id}: {exc}", path=path
            )
        exists = target.is_file()
        if absent:
            ok = not exists
            detail = f"{path} is absent" if ok else f"{path} still exists"
        else:
            ok = exists
            detail = f"{path} exists" if ok else f"{path} does not exist"
        content = ""
        if exists:
            try:
                content = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                content = ""
        return self._logged(
            step,
            check,
            action,
            approver,
            ok=ok,
            detail=f"{check.id}: {detail}",
            path=path,
            content=content,
        )

    def _file_contains(self, step: Step, check: Check) -> CheckResult:
        path = (check.path or "").strip()
        expected = check.contains if check.contains is not None else ""
        if not path:
            return self._finish(step, check, ok=False, detail=f"{check.id}: path is required")
        if expected == "":
            return self._finish(step, check, ok=False, detail=f"{check.id}: contains is required")
        action = _read_action(check, path)
        allowed, approver, action = self._authorize(action)
        if not allowed:
            return self._denied(step, check, action, approver)
        try:
            text = self.sandbox.read_file(path)
        except (SandboxError, FileNotFoundError, OSError) as exc:
            return self._logged(
                step,
                check,
                action,
                approver,
                ok=False,
                detail=f"{check.id}: {path} could not be read: {_read_failure(exc)}",
                path=path,
            )
        ok = expected in text
        detail = (
            f"{check.id}: {path} contains the expected text"
            if ok
            else f"{check.id}: {path} does not contain the expected text"
        )
        return self._logged(
            step,
            check,
            action,
            approver,
            ok=ok,
            detail=detail,
            path=path,
            content=text,
        )

    def _command(self, step: Step, check: Check) -> CheckResult:
        command = (check.command or "").strip()
        if not command:
            return self._finish(step, check, ok=False, detail=f"{check.id}: command is required")
        expected = 0 if check.expected_exit is None else check.expected_exit
        action = ActionRequest(
            kind=ActionKind.RUN_COMMAND.value,
            summary=f"check {command}",
            risk=_initial_risk("run_shell", {"command": command}),
            target=command,
            arguments={"command": command, "check": True},
        )
        allowed, approver, action = self._authorize(action)
        if not allowed:
            return self._denied(step, check, action, approver)
        timeout = check.timeout if check.timeout is not None else DEFAULT_CHECK_TIMEOUT
        result = self.sandbox.run(command, timeout=timeout)
        ok = result.exit_code == expected
        if result.timed_out:
            detail = f"{check.id}: command timed out (exit {result.exit_code}, expected {expected})"
        else:
            detail = f"{check.id}: command exited {result.exit_code}, expected {expected}"
        return self._logged(
            step,
            check,
            action,
            approver,
            ok=ok,
            detail=detail,
            path=command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            tool="run_shell",
        )

    def _exit_code(self, step: Step, check: Check) -> CheckResult:
        """Compare the latest command evidence for this attempt. Does not re-run it."""
        expected = 0 if check.expected_exit is None else check.expected_exit
        shells = [
            item
            for item in self.ledger.for_step(step.id, attempt=current_attempt.get())
            if item.kind == "tool" and item.exit_code is not None
        ]
        if not shells:
            return self._finish(
                step,
                check,
                ok=False,
                detail=f"{check.id}: command never ran (expected exit {expected})",
                summary=describe_check(check),
            )
        last = shells[-1]
        ok = last.exit_code == expected
        detail = f"{check.id}: exit_code={last.exit_code}, expected {expected}"
        # Cite the tool evidence that already holds the output. Also record a
        # check row so a reader can see the comparison.
        cited = self._finish(
            step,
            check,
            ok=ok,
            detail=detail,
            summary=describe_check(check),
            exit_code=last.exit_code,
            extra_ids=[last.id],
        )
        return cited

    def _stdout(self, step: Step, check: Check) -> CheckResult:
        """Compare stdout from the latest command evidence for this step.

        Does not re-run the command. A redirect that left stdout empty fails
        a last-line or line-count requirement even when the exit code was 0.
        """
        chosen = _latest_output(self.ledger.for_step(step.id, attempt=current_attempt.get()))
        if chosen is None:
            return self._finish(
                step,
                check,
                ok=False,
                detail=f"{check.id}: command never ran",
                summary=describe_check(check),
            )
        lines = [line for line in chosen.stdout.splitlines() if line.strip()]
        problems: list[str] = []
        if check.stdout_last_line is not None:
            expected = check.stdout_last_line.strip()
            actual = lines[-1].strip() if lines else ""
            if actual != expected:
                problems.append(f"last line is {actual!r}, expected {expected!r}")
        if check.stdout_line_count is not None:
            if len(lines) != check.stdout_line_count:
                problems.append(f"{len(lines)} lines, expected {check.stdout_line_count}")
        ok = not problems
        detail = (
            f"{check.id}: output matched"
            if ok
            else f"{check.id}: " + "; ".join(problems)
        )
        return self._finish(
            step,
            check,
            ok=ok,
            detail=detail,
            summary=describe_check(check),
            exit_code=chosen.exit_code,
            extra_ids=[chosen.id],
        )

    def _json_schema(self, step: Step, check: Check) -> CheckResult:
        path = (check.path or "").strip()
        if not path:
            return self._finish(step, check, ok=False, detail=f"{check.id}: path is required")
        action = _read_action(check, path)
        allowed, approver, action = self._authorize(action)
        if not allowed:
            return self._denied(step, check, action, approver)
        try:
            text = self.sandbox.read_file(path)
        except (SandboxError, FileNotFoundError, OSError) as exc:
            return self._logged(
                step,
                check,
                action,
                approver,
                ok=False,
                detail=f"{check.id}: {path} could not be read: {_read_failure(exc)}",
                path=path,
            )
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            return self._logged(
                step,
                check,
                action,
                approver,
                ok=False,
                detail=f"{check.id}: {path} is not JSON: {exc.msg}",
                path=path,
                content=text,
            )
        problem = _schema_error(loaded, check.json_schema or {})
        ok = problem is None
        detail = f"{check.id}: {path} matches the schema" if ok else f"{check.id}: {path} {problem}"
        return self._logged(
            step,
            check,
            action,
            approver,
            ok=ok,
            detail=detail,
            path=path,
            content=text,
        )

    def _denied(
        self,
        step: Step,
        check: Check,
        action: ActionRequest,
        approver: str,
    ) -> CheckResult:
        return self._logged(
            step,
            check,
            action,
            approver,
            ok=False,
            detail=f"{check.id}: check denied",
            approved=False,
        )

    def _logged(
        self,
        step: Step,
        check: Check,
        action: ActionRequest,
        approver: str,
        *,
        ok: bool,
        detail: str,
        approved: bool = True,
        path: str | None = None,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        content: str = "",
        tool: str | None = None,
    ) -> CheckResult:
        evidence = self.ledger.record_observation(
            step_id=step.id,
            kind="check",
            summary=describe_check(check),
            ok=ok,
            detail=detail,
            exit_code=exit_code,
            path=path if path is not None else check.path,
            stdout=stdout,
            stderr=stderr,
            content=content,
            tool=tool,
        )
        self._log(
            action,
            approved=approved,
            approver=approver,
            outcome=detail,
            evidence_id=evidence.id,
        )
        return CheckResult(
            check_id=check.id,
            passed=ok,
            evidence_ids=[evidence.id],
            detail=detail,
        )

    def _finish(
        self,
        step: Step,
        check: Check,
        *,
        ok: bool,
        detail: str,
        summary: str | None = None,
        exit_code: int | None = None,
        extra_ids: list[str] | None = None,
    ) -> CheckResult:
        evidence = self.ledger.record_observation(
            step_id=step.id,
            kind="check",
            summary=summary or describe_check(check),
            ok=ok,
            detail=detail,
            exit_code=exit_code,
            path=check.path,
        )
        ids = [evidence.id]
        for item in extra_ids or []:
            if item not in ids:
                ids.append(item)
        return CheckResult(check_id=check.id, passed=ok, evidence_ids=ids, detail=detail)

    def _authorize(self, action: ActionRequest) -> tuple[bool, str, ActionRequest]:
        """Return whether the check may run, the approver label, and the classified action."""
        policy = self.policy
        if policy is None:
            return True, "policy", action
        classified = policy.classify(action)
        if action.risk is RiskLevel.DESTRUCTIVE:
            classified = RiskLevel.DESTRUCTIVE
        if classified is not action.risk:
            action = action.model_copy(update={"risk": classified})
        decision = _policy_decision(policy, action)
        if decision == "deny":
            return False, "policy", action
        if decision == "prompt":
            approved = bool(self.prompter.prompt(action)) if self.prompter is not None else False
            return approved, "user", action
        if policy.autonomy is AutonomyLevel.AUTO:
            return True, "auto", action
        return True, "policy", action

    def _log(
        self,
        action: ActionRequest,
        *,
        approved: bool,
        approver: str,
        outcome: str,
        evidence_id: str | None,
    ) -> None:
        if self.on_action is None or self.policy is None:
            return
        self.on_action(
            ActionLogEntry(
                action=action,
                autonomy=self.policy.autonomy,
                approved=approved,
                approver=approver,
                outcome=outcome,
                evidence_id=evidence_id,
            )
        )


def _read_failure(exc: BaseException) -> str:
    """Stable check text. Exception messages include the absolute sandbox path."""
    if isinstance(exc, FileNotFoundError):
        return "file not found"
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return type(exc).__name__


def _read_action(check: Check, path: str) -> ActionRequest:
    return ActionRequest(
        kind=ActionKind.READ_FILE.value,
        summary=f"check {describe_check(check)}",
        risk=RiskLevel.READ,
        target=path,
        arguments={"path": path, "check": True},
    )


def _check_from_obj(entry: Any, index: int) -> Check:
    if isinstance(entry, str):
        derived = derive_checks(entry if ":" in entry else f"file_exists: {entry}")
        if len(derived) == 1:
            derived[0].id = derived[0].id or f"chk-{index}"
            return derived[0]
        raise PlanParseError(f"check {index} is not a check")
    if not isinstance(entry, dict):
        raise PlanParseError(f"check {index} must be an object")
    kind = entry.get("kind") or entry.get("type")
    if not isinstance(kind, str) or not kind.strip():
        raise PlanParseError(f"check {index} needs a kind")
    path = _optional_str(entry.get("path"))
    command = _optional_str(entry.get("command") or entry.get("cmd"))
    contains = entry.get("contains", entry.get("text"))
    if contains is not None:
        contains = str(contains)
    schema = entry.get("json_schema", entry.get("schema"))
    if schema is not None and not isinstance(schema, dict):
        raise PlanParseError(f"check {index} schema must be an object")
    requested = _optional_str(entry.get("id")) or f"chk-{index}"
    try:
        return Check(
            id=requested,
            kind=canonical_kind(kind),
            description=_optional_str(entry.get("description")) or "",
            path=path,
            command=command,
            contains=contains,
            expected_exit=entry.get("expected_exit", entry.get("exits")),
            json_schema=schema if isinstance(schema, dict) else None,
            timeout=entry.get("timeout"),
        )
    except ValueError as exc:
        raise PlanParseError(f"check {index} is invalid: {exc}") from exc


def _from_shorthand(kind_raw: str, body: str) -> Check | None:
    kind = canonical_kind(kind_raw)
    expected: int | None = None
    exits = _EXITS.search(body)
    if exits is not None:
        expected = int(exits.group(1))
        body = body[: exits.start()].strip()
    if kind == "command":
        if not body:
            return None
        return Check(
            kind=kind,
            command=body,
            expected_exit=expected,
            description=f"{kind_raw}: {body}",
        )
    if kind == "exit_code":
        if expected is None and body.lstrip("-").isdigit():
            expected = int(body)
        return Check(kind=kind, expected_exit=0 if expected is None else expected)
    if kind == "file_contains":
        parsed = _PATH_TEXT.match(body)
        if parsed is None:
            return None
        text = parsed.group("dq") or parsed.group("sq") or parsed.group("bare") or ""
        return Check(kind=kind, path=parsed.group("path"), contains=text.strip())
    if kind in {"file_exists", "file_absent", "json_schema"}:
        path = body.split()[0] if body.split() else ""
        if not path:
            return None
        return Check(kind=kind, path=path)
    return None


def _schema_error(value: Any, schema: dict[str, Any]) -> str | None:
    """A small subset of JSON Schema: type, required, and properties.

    Returns None when ``value`` matches. An empty schema only requires the
    file to be JSON, which the caller already parsed.
    """
    if not schema:
        return None
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return "expected a JSON object"
        required = schema.get("required") or []
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    return f"missing required key {key!r}"
        properties = schema.get("properties") or {}
        if isinstance(properties, dict):
            for key, sub in properties.items():
                if key in value and isinstance(sub, dict):
                    nested = _schema_error(value[key], sub)
                    if nested:
                        return f"{key}: {nested}"
        return None
    if expected == "array" and not isinstance(value, list):
        return "expected a JSON array"
    if expected == "string" and not isinstance(value, str):
        return "expected a string"
    if expected == "number" and (isinstance(value, bool) or not isinstance(value, int | float)):
        return "expected a number"
    if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        return "expected an integer"
    if expected == "boolean" and not isinstance(value, bool):
        return "expected a boolean"
    if expected == "null" and value is not None:
        return "expected null"
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

