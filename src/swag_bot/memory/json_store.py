"""JSON-file ``MemoryStore``.

Useful in tests and anywhere a single readable file is enough. Search matches
the process-local fake: case-insensitive substring over content and metadata
values, newest first. An empty query returns nothing.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from swag_bot.interfaces import MemoryItem
from swag_bot.memory.errors import MemoryError
from swag_bot.memory.util import haystack


class JsonFileMemoryStore:
    """One JSON document on disk. Writes are atomic."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        """Append one item and return it."""
        meta = dict(metadata or {})
        _ensure_jsonable(meta)
        item = MemoryItem(
            id=uuid4().hex,
            content=content,
            metadata=meta,
            created_at=datetime.now(UTC),
        )
        items = self._load()
        items.append(item)
        self._save(items)
        return item

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        """Case-insensitive substring, newest first."""
        if limit <= 0 or not query.strip():
            return []
        needle = query.casefold()
        matches = [item for item in self._load() if needle in haystack(item)]
        matches.sort(key=lambda item: item.created_at, reverse=True)
        return matches[:limit]

    def get(self, item_id: str) -> MemoryItem | None:
        """Return one item, or None when the id is missing."""
        for item in self._load():
            if item.id == item_id:
                return item
        return None

    def delete(self, item_id: str) -> bool:
        """Delete one item. Return True only if it existed."""
        items = self._load()
        kept = [item for item in items if item.id != item_id]
        if len(kept) == len(items):
            return False
        self._save(kept)
        return True

    def list_recent(self, *, limit: int = 20) -> list[MemoryItem]:
        """Newest items. Used by ``swag memory list``."""
        if limit <= 0:
            return []
        items = self._load()
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    def _load(self) -> list[MemoryItem]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MemoryError(f"cannot read {self.path}: {exc}") from exc
        rows = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            raise MemoryError(f"cannot read {self.path}: expected an items list")
        items: list[MemoryItem] = []
        for row in rows:
            if isinstance(row, dict):
                items.append(MemoryItem.model_validate(row))
        return items

    def _save(self, items: list[MemoryItem]) -> None:
        payload = {
            "items": [
                {
                    "id": item.id,
                    "content": item.content,
                    "metadata": item.metadata,
                    "created_at": item.created_at.isoformat(),
                }
                for item in items
            ]
        }
        text = json.dumps(payload, indent=2)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, self.path)


def _ensure_jsonable(metadata: Mapping[str, Any]) -> None:
    try:
        json.dumps(metadata)
    except TypeError as exc:
        raise MemoryError("memory metadata must be JSON serializable") from exc
