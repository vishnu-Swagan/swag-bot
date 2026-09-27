"""Describe the memory backend ``swag doctor`` should print.

The config key ``memory`` is the SQLite file ``$SWAG_HOME/memory.db``. An
empty ``memory.path`` is that default, not "no path".
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from swag_bot.config import Settings
from swag_bot.memory.factory import KNOWN_BACKENDS, SQLITE_BACKENDS, resolve_memory_path

_DEFAULT_AGENTMEMORY = "http://127.0.0.1:3111"


@dataclass(frozen=True)
class MemoryDescription:
    """Rows for the doctor table. Paths are resolved, not the raw config string."""

    backend_label: str
    path_label: str
    mode: str


def describe_memory(settings: Settings) -> MemoryDescription:
    """Resolve backend, file, and mode without creating the database."""
    configured = settings.memory.backend.strip().lower() or "memory"
    mode = settings.memory.mode
    if configured in SQLITE_BACKENDS:
        path = resolve_memory_path(settings, "memory.db")
        state = "present" if path.is_file() else "not created yet"
        return MemoryDescription(
            backend_label=f"sqlite (config: {configured})",
            path_label=f"{path} ({state})",
            mode=mode,
        )
    if configured == "json":
        path = resolve_memory_path(settings, "memory.json")
        state = "present" if path.is_file() else "not created yet"
        return MemoryDescription(
            backend_label="json (config: json)",
            path_label=f"{path} ({state})",
            mode=mode,
        )
    if configured == "agentmemory":
        return MemoryDescription(
            backend_label="agentmemory (config: agentmemory)",
            path_label=f"{_agentmemory_url(settings)} (remote)",
            mode=mode,
        )
    if configured not in KNOWN_BACKENDS:
        shown = (settings.memory.path or "").strip() or "(none)"
        return MemoryDescription(
            backend_label=f"unknown (config: {configured})",
            path_label=shown,
            mode=mode,
        )
    shown = (settings.memory.path or "").strip() or "(none)"
    return MemoryDescription(
        backend_label=configured,
        path_label=shown,
        mode=mode,
    )


def _agentmemory_url(settings: Settings) -> str:
    """URL the agentmemory backend would use. Does not read the bearer secret."""
    configured = (settings.memory.path or "").strip()
    if configured.startswith(("http://", "https://")):
        return configured
    return os.environ.get("AGENTMEMORY_URL", "").strip() or _DEFAULT_AGENTMEMORY
