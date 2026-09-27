"""SQLite memory: FTS5, tags, timestamps, and the substring fallback."""

from __future__ import annotations

from pathlib import Path

from swag_bot.memory.sqlite import SQLiteMemoryStore


def test_add_search_get_delete_matches_the_contract(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    assert store._fts is True
    first = store.add("Alpha note", metadata={"tag": "docs"})
    second = store.add("beta ALPHA", metadata={"tag": "other"})
    assert store.get(first.id) == first
    assert store.get("missing") is None
    found = store.search("alpha")
    assert {item.id for item in found} == {first.id, second.id}
    # A partial token misses FTS and keeps the newest-first substring order.
    assert [item.id for item in store.search("alp")] == [second.id, first.id]
    assert store.search("docs")[0].id == first.id
    assert store.search("   ") == []
    assert store.search("alpha", limit=0) == []
    assert store.delete(first.id) is True
    assert store.delete(first.id) is False
    assert store.get(first.id) is None


def test_tags_and_timestamps_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "memory.db"
    store = SQLiteMemoryStore(path)
    item = store.add("ship the release", metadata={"tags": ["release", "ops"]})
    assert item.created_at.tzinfo is not None
    assert store.search("release")[0].id == item.id
    assert store.search("ops")[0].id == item.id
    store.close()
    again = SQLiteMemoryStore(path)
    loaded = again.get(item.id)
    assert loaded is not None
    assert loaded.created_at == item.created_at
    assert loaded.metadata["tags"] == ["release", "ops"]
    listed = again.list_recent()
    assert listed[0].id == item.id


def test_substring_fallback_is_newest_first(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    first = store.add("alpha one")
    second = store.add("alpha two")
    # "alp" is not a whole token, so FTS misses it and substring order applies.
    assert [item.id for item in store.search("alp")] == [second.id, first.id]


def test_fts_prefix_and_relevance(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    short = store.add("fox")
    store.add("fox " + ("padding " * 40))
    # The asterisk is not in the text. Only an FTS prefix query finds "fox".
    prefixed = store.search("fox*")
    assert prefixed
    assert prefixed[0].id == short.id
    ranked = store.search("fox")
    assert ranked[0].id == short.id
