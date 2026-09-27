"""Reversibility labels for the jury gate.

The names match the undo ledger in draft PR #10
(``cursor/undo-ledger-d431``):

- ``reversible``: a workspace read or write, including a shell command that
  stays inside the workdir. A snapshot can put the files back.
- ``compensable``: an external effect that has a registered inverse, such as
  closing an issue the tool just opened.
- ``irreversible``: a point of no return. Sending mail, spending money,
  publishing, or writing outside the workdir cannot be undone from here.

This module is a stub so escalation can merge before that ledger does.
``swag run`` loads the safety package's classifier when that module exists,
and uses :class:`StubReversibilityClassifier` otherwise.

The stub does not trust tool arguments. A model can put anything in them,
including a claim that a payment is reversible. An explicit label is honored
only when a trusted caller set ``action.reversibility`` (the undo ledger
stamps that field). Compensable actions come from that stamp or from the
real classifier, which knows the compensation registry.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from swag_bot.interfaces import ActionRequest, RiskLevel

_READ_KINDS = frozenset({"read_file", "list_dir", "memory", "search"})
_WRITE_KINDS = frozenset({"write_file", "edit_file", "create_file", "delete", "unlink"})
_SHELL_KINDS = frozenset({"run_command", "shell", "exec", "bash", "run_shell"})
_EXTERNAL_KINDS = frozenset(
    {
        "network",
        "http",
        "fetch",
        "send_message",
        "message",
        "email",
        "spend",
        "payment",
        "purchase",
        "billing",
    }
)

_NETWORK = re.compile(
    r"(?i)\b(?:curl|wget|ssh|scp|sftp|nc|ncat|sendmail|mailx)\b|https?://"
)
_PUBLISH = re.compile(
    r"(?i)\b(?:git\s+push|npm\s+publish|pnpm\s+publish|yarn\s+publish|"
    r"docker\s+push|twine\s+upload|cargo\s+publish)\b"
)
_SEND = re.compile(r"(?i)\b(?:send(?:ing)?\s+(?:an?\s+)?(?:message|email|mail)|mail\s+-s)\b")
_SPEND = re.compile(
    r"(?i)\b(?:spend(?:ing)?\s+money|purchase|payment|wire\s+transfer|credit card)\b"
)
_ABSOLUTE_MUTATION = re.compile(
    r"(?i)(?:^|[;&|`(])\s*(?:sudo\s+)?"
    r"(?:rm|rmdir|unlink|mv|cp|dd|shred)\b[^;&|]*\s+/(?!dev/null\b)"
)


class Reversibility(StrEnum):
    """Whether an action can be undone. Values match the undo ledger."""

    REVERSIBLE = "reversible"
    COMPENSABLE = "compensable"
    IRREVERSIBLE = "irreversible"


@runtime_checkable
class ReversibilityClassifier(Protocol):
    """Map one action to a reversibility label."""

    def classify(self, action: ActionRequest) -> Reversibility:
        """Return ``reversible``, ``compensable``, or ``irreversible``."""
        ...


class StubReversibilityClassifier:
    """Small stand-in for ``safety.reversibility.classify_reversibility``.

    Workspace reads and writes are reversible. Shell commands that reach the
    network, publish, send mail, spend money, or mutate an absolute path are
    irreversible. Anything else external is irreversible too: the jury should
    see an unknown side effect rather than assume it can be undone.
    """

    def classify(self, action: ActionRequest) -> Reversibility:
        declared = read_declared_reversibility(action)
        if declared is not None:
            return declared
        return classify_stub(action)


def read_declared_reversibility(action: object) -> Reversibility | None:
    """Return a label a trusted caller already stored on ``action``.

    Tool arguments are ignored. Only the ``reversibility`` attribute counts,
    which is the field the undo ledger adds to ``ActionRequest``.
    """
    raw = getattr(action, "reversibility", None)
    if raw is None:
        return None
    text = str(getattr(raw, "value", raw)).strip().casefold()
    try:
        return Reversibility(text)
    except ValueError:
        return None


def classify_stub(action: ActionRequest) -> Reversibility:
    """Heuristic label. Does not consult a compensation registry."""
    kind = action.kind.strip().casefold()
    if kind in _READ_KINDS and action.risk is RiskLevel.READ:
        return Reversibility.REVERSIBLE
    if kind in _WRITE_KINDS:
        if _path_escapes(_file_target(action)):
            return Reversibility.IRREVERSIBLE
        return Reversibility.REVERSIBLE
    if kind in _SHELL_KINDS:
        command = _command_text(action)
        if not command or command_is_irreversible(command):
            return Reversibility.IRREVERSIBLE
        return Reversibility.REVERSIBLE
    if kind in _EXTERNAL_KINDS:
        return Reversibility.IRREVERSIBLE
    return Reversibility.IRREVERSIBLE


def command_is_irreversible(command: str) -> bool:
    """True when a shell command likely leaves the snapshotted workdir."""
    if _NETWORK.search(command) or _PUBLISH.search(command):
        return True
    if _SEND.search(command) or _SPEND.search(command):
        return True
    return _ABSOLUTE_MUTATION.search(command) is not None


def adapt_classifier(
    classify_reversibility: object,
    workdir: Path | None = None,
) -> ReversibilityClassifier:
    """Wrap another package's ``classify_reversibility`` in this protocol.

    A missing or non-callable function returns the stub. The composition root
    is what imports that function; this module does not.
    """
    if not callable(classify_reversibility):
        return StubReversibilityClassifier()
    return _ImportedClassifier(classify_reversibility, workdir)


class _ImportedClassifier:
    """Adapt ``classify_reversibility(action, workdir=...)`` to our protocol."""

    def __init__(self, classify_reversibility: object, workdir: Path | None) -> None:
        self._classify = classify_reversibility
        self._workdir = workdir

    def classify(self, action: ActionRequest) -> Reversibility:
        result = _call(self._classify, action, self._workdir)
        raw = getattr(result, "value", result)
        try:
            return Reversibility(str(raw))
        except ValueError:
            return Reversibility.IRREVERSIBLE


def _call(fn: object, action: ActionRequest, workdir: Path | None) -> object:
    if not callable(fn):
        return Reversibility.IRREVERSIBLE
    caller = cast(Callable[..., object], fn)
    try:
        return caller(action, workdir=workdir)
    except TypeError:
        return caller(action)


def _file_target(action: ActionRequest) -> str | None:
    if action.target:
        return action.target
    path = action.arguments.get("path")
    if isinstance(path, str):
        return path
    return None


def _command_text(action: ActionRequest) -> str:
    if action.target:
        return action.target
    command = action.arguments.get("command")
    if isinstance(command, str):
        return command
    return ""


def _path_escapes(target: str | None) -> bool:
    if not target:
        return False
    path = Path(target)
    return path.is_absolute() or ".." in path.parts
