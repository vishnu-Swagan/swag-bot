"""Memory factory selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from swag_bot.config import MemorySettings, Settings, swag_home
from swag_bot.errors import ConfigError
from swag_bot.interfaces import MemoryStore
from swag_bot.memory import get_memory_store
from swag_bot.memory.agentmemory import AgentMemoryStore
from swag_bot.memory.json_store import JsonFileMemoryStore
from swag_bot.memory.sqlite import SQLiteMemoryStore


def test_default_backend_is_sqlite_under_swag_home() -> None:
    store = get_memory_store(Settings())
    assert isinstance(store, SQLiteMemoryStore)
    assert isinstance(store, MemoryStore)
    assert store.path == swag_home() / "memory.db"
    assert store.path.is_file()


def test_relative_and_absolute_sqlite_paths(tmp_path: Path) -> None:
    relative = get_memory_store(
        Settings(memory=MemorySettings(backend="sqlite", path="notes/mem.db"))
    )
    assert isinstance(relative, SQLiteMemoryStore)
    assert relative.path == swag_home() / "notes" / "mem.db"
    absolute = get_memory_store(
        Settings(memory=MemorySettings(backend="memory", path=str(tmp_path / "abs.db")))
    )
    assert isinstance(absolute, SQLiteMemoryStore)
    assert absolute.path == tmp_path / "abs.db"


def test_json_and_agentmemory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTMEMORY_URL", raising=False)
    monkeypatch.delenv("AGENTMEMORY_TRANSPORT", raising=False)
    json_store = get_memory_store(Settings(memory=MemorySettings(backend="json")))
    assert isinstance(json_store, JsonFileMemoryStore)
    assert json_store.path == swag_home() / "memory.json"
    remote = get_memory_store(
        Settings(memory=MemorySettings(backend="agentmemory", path="http://127.0.0.1:3111"))
    )
    assert isinstance(remote, AgentMemoryStore)
    assert remote.transport_name == "rest"


def test_unknown_backend() -> None:
    with pytest.raises(ConfigError, match="unknown memory backend"):
        get_memory_store(Settings(memory=MemorySettings(backend="redis")))
