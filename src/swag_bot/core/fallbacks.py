"""Stand-ins used by ``swag run`` until the other packages ship their factories.

The loop itself never constructs these. The CLI does, and only when a factory
raises ``NotImplementedYet``. Tests inject the fakes in ``tests/fakes.py``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer

from swag_bot.interfaces import (
    TIMEOUT_EXIT_CODE,
    ActionRequest,
    AutonomyLevel,
    CommandResult,
    MemoryItem,
    RiskLevel,
    default_requires_approval,
    resolve_sandbox_path,
)


class LocalSandbox:
    """Run shell commands and read or write UTF-8 files inside one directory."""

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir
        self._workdir.mkdir(parents=True, exist_ok=True)

    @property
    def workdir(self) -> Path:
        return self._workdir

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=self._workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                exit_code=TIMEOUT_EXIT_CODE,
                stdout=_text(exc.stdout),
                stderr=_text(exc.stderr),
                timed_out=True,
            )
        return CommandResult(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def read_file(self, path: str) -> str:
        target = resolve_sandbox_path(self._workdir, path)
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        target = resolve_sandbox_path(self._workdir, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class FallbackMemory:
    """Process-local memory. Search is a case-insensitive substring, newest first."""

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        item = MemoryItem(
            id=uuid4().hex,
            content=content,
            metadata=dict(metadata or {}),
            created_at=datetime.now(UTC),
        )
        self._items[item.id] = item
        return item

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        if limit <= 0 or not query.strip():
            return []
        needle = query.casefold()
        matches = [item for item in self._items.values() if needle in _haystack(item)]
        matches.sort(key=lambda item: item.created_at, reverse=True)
        return matches[:limit]

    def get(self, item_id: str) -> MemoryItem | None:
        return self._items.get(item_id)

    def delete(self, item_id: str) -> bool:
        return self._items.pop(item_id, None) is not None


class FallbackPolicy:
    """Autonomy from settings, classified with ``default_requires_approval``."""

    def __init__(self, autonomy: AutonomyLevel) -> None:
        self._autonomy = autonomy

    @property
    def autonomy(self) -> AutonomyLevel:
        return self._autonomy

    def classify(self, action: ActionRequest) -> RiskLevel:
        return action.risk

    def requires_approval(self, action: ActionRequest) -> bool:
        return default_requires_approval(self.autonomy, self.classify(action))


class FallbackPrompter:
    """Ask on the terminal. A denied or closed prompt returns False."""

    def prompt(self, action: ActionRequest) -> bool:
        question = f"Allow {action.risk.value} action: {action.summary}?"
        try:
            return bool(typer.confirm(question, default=False))
        except (EOFError, KeyboardInterrupt):
            return False


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _haystack(item: MemoryItem) -> str:
    parts = [item.content]
    parts.extend(str(entry) for entry in item.metadata.values())
    return "\n".join(parts).casefold()
