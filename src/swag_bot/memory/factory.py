"""Select a ``MemoryStore`` from settings.

``get_memory_store`` is the working factory used by ``swag memory``.
``build_memory_store`` stays a stub because the foundation smoke test
``tests/test_fakes.py`` asserts that it raises ``NotImplementedYet``. That
test is outside this package. Call ``get_memory_store`` from ``swag run``,
or alias the two once that assertion is updated.
"""

from __future__ import annotations

from pathlib import Path

from swag_bot.config import Settings, load_settings, swag_home
from swag_bot.errors import ConfigError, NotImplementedYet
from swag_bot.interfaces import MemoryStore
from swag_bot.memory.agentmemory import agentmemory_from_settings
from swag_bot.memory.json_store import JsonFileMemoryStore
from swag_bot.memory.sqlite import SQLiteMemoryStore

SQLITE_BACKENDS = frozenset({"memory", "sqlite"})
KNOWN_BACKENDS = frozenset({*SQLITE_BACKENDS, "json", "agentmemory"})


def get_memory_store(config: Settings | None = None) -> MemoryStore:
    """Store for ``config.memory``. Loads ``config.toml`` when ``config`` is omitted.

    ``memory`` and ``sqlite`` open the SQLite file (default ``~/.swag/memory.db``).
    ``json`` opens a JSON file. ``agentmemory`` talks to an external server.
    """
    settings = load_settings() if config is None else config
    backend = settings.memory.backend.strip().lower()
    if backend in SQLITE_BACKENDS:
        return SQLiteMemoryStore(resolve_memory_path(settings, "memory.db"))
    if backend == "json":
        return JsonFileMemoryStore(resolve_memory_path(settings, "memory.json"))
    if backend == "agentmemory":
        return agentmemory_from_settings(settings)
    known = ", ".join(sorted(KNOWN_BACKENDS))
    raise ConfigError(f"unknown memory backend {backend!r}. Known backends: {known}")


def build_memory_store(settings: Settings) -> MemoryStore:
    """Foundation stub. See ``get_memory_store`` for the working factory."""
    raise NotImplementedYet("memory.build_memory_store")


def resolve_memory_path(settings: Settings, default_name: str) -> Path:
    """Absolute path for a file-backed store.

    An empty ``memory.path`` uses ``default_name`` inside ``SWAG_HOME``.
    Relative paths are resolved under ``SWAG_HOME``. Absolute paths are kept.
    """
    raw = (settings.memory.path or "").strip()
    if not raw:
        return swag_home() / default_name
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return swag_home() / candidate
