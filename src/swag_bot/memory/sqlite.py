"""SQLite memory with FTS5, tags, and timestamps.

This is the default on-disk store. The backend name ``memory`` (the config
default) and ``sqlite`` both open it. The file is ``~/.swag/memory.db`` unless
``settings.memory.path`` says otherwise. Relative paths resolve under
``SWAG_HOME``. Nothing here uses the network.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from swag_bot.interfaces import MemoryItem
from swag_bot.memory.errors import MemoryError
from swag_bot.memory.util import metadata_blob, tags_from_metadata

_TOKEN = re.compile(r"\w+\*?")


class SQLiteMemoryStore:
    """``MemoryStore`` backed by a single SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fts = False
        self._setup()

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        """Insert one memory and return it."""
        meta = dict(metadata or {})
        item = MemoryItem(
            id=uuid4().hex,
            content=content,
            metadata=meta,
            created_at=datetime.now(UTC),
        )
        tags = " ".join(tags_from_metadata(meta))
        blob = metadata_blob(meta)
        encoded = _dump_metadata(meta)
        created = item.created_at.isoformat()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO memories (id, content, metadata, tags, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (item.id, item.content, encoded, tags, created),
            )
            if self._fts:
                self._conn.execute(
                    """
                    INSERT INTO memories_fts (id, content, tags, metadata_text)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item.id, item.content, tags, blob),
                )
        return item

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        """Best-first matches. An empty query returns nothing.

        FTS5 hits come first, ordered by bm25 (lower is better) and then by
        newer ``created_at``. Substring hits that FTS did not return follow,
        newest first. Substring search covers content, the tags column, and
        the metadata JSON, so a partial word still matches.
        """
        if limit <= 0 or not query.strip():
            return []
        needle = query.strip()
        with self._lock:
            ordered: list[str] = []
            seen: set[str] = set()
            for item_id in self._fts_ids(needle):
                if item_id not in seen:
                    seen.add(item_id)
                    ordered.append(item_id)
            for item_id in self._substring_ids(needle):
                if item_id not in seen:
                    seen.add(item_id)
                    ordered.append(item_id)
            found: list[MemoryItem] = []
            for item_id in ordered[:limit]:
                item = self._get_unlocked(item_id)
                if item is not None:
                    found.append(item)
            return found

    def get(self, item_id: str) -> MemoryItem | None:
        """Return one item, or None when the id is missing."""
        with self._lock:
            return self._get_unlocked(item_id)

    def delete(self, item_id: str) -> bool:
        """Delete one item. Return True only if it existed."""
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT 1 FROM memories WHERE id = ?",
                (item_id,),
            ).fetchone()
            if existing is None:
                return False
            self._conn.execute("DELETE FROM memories WHERE id = ?", (item_id,))
            if self._fts:
                self._conn.execute("DELETE FROM memories_fts WHERE id = ?", (item_id,))
            return True

    def list_recent(self, *, limit: int = 20) -> list[MemoryItem]:
        """Newest items, ignoring the search query. Used by ``swag memory list``."""
        if limit <= 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_row_to_item(row) for row in rows]

    def close(self) -> None:
        """Close the database. Safe to call more than once."""
        with self._lock:
            self._conn.close()

    def _setup(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        metadata TEXT NOT NULL,
                        tags TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)"
                )
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                            id UNINDEXED,
                            content,
                            tags,
                            metadata_text
                        )
                        """
                    )
            except sqlite3.OperationalError:
                self._fts = False
            else:
                self._fts = True

    def _fts_ids(self, query: str) -> list[str]:
        if not self._fts:
            return []
        match = _fts_query(query)
        if not match:
            return []
        try:
            rows = self._conn.execute(
                """
                SELECT memories_fts.id AS id
                FROM memories_fts
                JOIN memories ON memories.id = memories_fts.id
                WHERE memories_fts MATCH ?
                ORDER BY bm25(memories_fts), memories.created_at DESC
                """,
                (match,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [str(row["id"]) for row in rows]

    def _substring_ids(self, query: str) -> list[str]:
        needle = query.casefold()
        rows = self._conn.execute(
            """
            SELECT id FROM memories
            WHERE instr(lower(content), ?) > 0
               OR instr(lower(metadata), ?) > 0
               OR instr(lower(tags), ?) > 0
            ORDER BY created_at DESC
            """,
            (needle, needle, needle),
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def _get_unlocked(self, item_id: str) -> MemoryItem | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        return _row_to_item(row)


def _fts_query(query: str) -> str | None:
    """Quote each word for FTS5. A trailing ``*`` on a word is a prefix query."""
    parts: list[str] = []
    for token in _TOKEN.findall(query):
        if token.endswith("*"):
            word = token[:-1]
            if word:
                parts.append(f'"{word}"*')
        else:
            parts.append(f'"{token}"')
    if not parts:
        return None
    return " OR ".join(parts)


def _dump_metadata(metadata: Mapping[str, Any]) -> str:
    try:
        return json.dumps(metadata, separators=(",", ":"), sort_keys=True)
    except TypeError as exc:
        raise MemoryError("memory metadata must be JSON serializable") from exc


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    raw_meta = row["metadata"]
    try:
        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else {}
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    created = datetime.fromisoformat(row["created_at"])
    return MemoryItem(
        id=row["id"],
        content=row["content"],
        metadata=metadata,
        created_at=created,
    )
