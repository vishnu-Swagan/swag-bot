"""Append-only action log (JSONL)."""

from __future__ import annotations

from pathlib import Path

from swag_bot.config import swag_home
from swag_bot.errors import SwagError
from swag_bot.interfaces import (
    ActionLogEntry,
    ActionRequest,
    ApprovalPrompter,
    AutonomyLevel,
    PermissionPolicy,
)
from swag_bot.safety.policy import PolicyDecision
from swag_bot.safety.redact import redact_text, redact_value


def default_action_log_path() -> Path:
    """JSONL file under ``SWAG_HOME``."""
    return swag_home() / "actions.jsonl"


class ActionLog:
    """Append ``ActionLogEntry`` records. There is no delete or rewrite."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = default_action_log_path() if path is None else path

    def append(self, entry: ActionLogEntry) -> ActionLogEntry:
        """Redact secrets, append one JSON line, and return the stored entry."""
        stored = _redact_entry(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(stored.model_dump_json() + "\n")
        return stored

    def read(self) -> list[ActionLogEntry]:
        """Return every entry in append order. A missing file is an empty log."""
        if not self.path.is_file():
            return []
        entries: list[ActionLogEntry] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entries.append(ActionLogEntry.model_validate_json(line))
            except ValueError as exc:
                raise SwagError(f"bad action log line {number} in {self.path}: {exc}") from exc
        return entries


def redact_action(action: ActionRequest) -> ActionRequest:
    """Copy ``action`` with secrets removed from the summary, target, and arguments."""
    target = redact_text(action.target) if action.target is not None else None
    arguments = redact_value(action.arguments)
    if not isinstance(arguments, dict):
        arguments = {}
    return action.model_copy(
        update={
            "summary": redact_text(action.summary),
            "target": target,
            "arguments": arguments,
        }
    )


def _redact_entry(entry: ActionLogEntry) -> ActionLogEntry:
    outcome = redact_text(entry.outcome) if entry.outcome is not None else None
    return entry.model_copy(update={"action": redact_action(entry.action), "outcome": outcome})


def authorize(
    action: ActionRequest,
    *,
    policy: PermissionPolicy,
    prompter: ApprovalPrompter,
    log: ActionLog | None = None,
    outcome: str | None = None,
) -> bool:
    """Classify, maybe prompt, append a log line, and return whether to proceed.

    Secrets are redacted before the prompt and before the log. A policy that
    implements ``decide`` may hard-deny with no prompt. Otherwise the result
    follows ``requires_approval``.
    """
    safe = redact_action(action)
    risk = policy.classify(safe)
    stamped = safe.model_copy(update={"risk": risk})
    decision = _decision(policy, stamped)
    if decision is PolicyDecision.DENY:
        approved = False
        approver = "policy"
    elif decision is PolicyDecision.PROMPT:
        approved = bool(prompter.prompt(stamped))
        approver = "user"
    else:
        approved = True
        approver = "auto" if policy.autonomy is AutonomyLevel.AUTO else "policy"
    if log is not None:
        log.append(
            ActionLogEntry(
                action=stamped,
                autonomy=policy.autonomy,
                approved=approved,
                approver=approver,
                outcome=outcome,
            )
        )
    return approved


def _decision(policy: PermissionPolicy, action: ActionRequest) -> PolicyDecision:
    decide = getattr(policy, "decide", None)
    if callable(decide):
        raw = decide(action)
        if isinstance(raw, PolicyDecision):
            return raw
        if raw in {item.value for item in PolicyDecision}:
            return PolicyDecision(str(raw))
    if policy.requires_approval(action):
        return PolicyDecision.PROMPT
    return PolicyDecision.ALLOW
