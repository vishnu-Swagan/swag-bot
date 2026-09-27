"""JSON-file memory store."""

from __future__ import annotations

from pathlib import Path

import pytest

from swag_bot.memory.errors import MemoryError
from swag_bot.memory.json_store import JsonFileMemoryStore


def test_round_trip_and_search(tmp_path: Path) -> None:
    path = tmp_path / "mem.json"
    store = JsonFileMemoryStore(path)
    first = store.add("Alpha note", metadata={"tag": "docs"})
    second = store.add("beta ALPHA", metadata={"tag": "other"})
    assert store.search("alpha")[0].id == second.id
    assert store.search("docs")[0].id == first.id
    assert store.search(" ") == []
    assert store.get("missing") is None
    assert store.delete(first.id) is True
    assert store.delete(first.id) is False

    reloaded = JsonFileMemoryStore(path)
    assert reloaded.get(first.id) is None
    kept = reloaded.get(second.id)
    assert kept is not None
    assert kept.content == second.content
    assert kept.created_at == second.created_at
    assert reloaded.list_recent(limit=1)[0].id == second.id


def test_corrupt_file_and_bad_metadata(tmp_path: Path) -> None:
    path = tmp_path / "mem.json"
    path.write_text("{", encoding="utf-8")
    store = JsonFileMemoryStore(path)
    with pytest.raises(MemoryError):
        store.search("anything")
    fresh = JsonFileMemoryStore(tmp_path / "other.json")
    with pytest.raises(MemoryError):
        fresh.add("nope", metadata={"when": object()})
