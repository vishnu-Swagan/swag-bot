"""Commands the user already allowed during this run.

A goal check re-runs the command the step just ran. That is a new action, so
the policy would ask again. An exact command already approved in this run
does not need another prompt.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_approved: ContextVar[set[str] | None] = ContextVar("swag_approved_commands", default=None)


def normalize_command(command: str) -> str:
    """Collapse whitespace so a repeated command compares equal."""
    return " ".join(command.split())


@contextmanager
def approval_scope() -> Iterator[set[str]]:
    """Remember approvals for one run, then drop them."""
    bucket: set[str] = set()
    token = _approved.set(bucket)
    try:
        yield bucket
    finally:
        _approved.reset(token)


def remember_approved_command(command: str) -> None:
    """Record one shell command the run was allowed to execute."""
    bucket = _approved.get()
    text = normalize_command(command)
    if bucket is None or not text:
        return
    bucket.add(text)


def command_already_approved(command: str) -> bool:
    """True when this run already approved ``command`` exactly."""
    bucket = _approved.get()
    if not bucket:
        return False
    return normalize_command(command) in bucket
