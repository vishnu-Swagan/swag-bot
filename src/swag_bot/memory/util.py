"""Shared helpers for memory backends. No network and no other owned packages."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from swag_bot.interfaces import MemoryItem


def tags_from_metadata(metadata: Mapping[str, Any]) -> list[str]:
    """Tags from ``tags`` or ``tag``. Strings split on commas; lists are flattened."""
    raw = metadata.get("tags", metadata.get("tag"))
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]
    text = str(raw).strip()
    return [text] if text else []


def metadata_blob(metadata: Mapping[str, Any]) -> str:
    """Space-separated metadata values for full-text indexing."""
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, bool) or value is None:
            return
        else:
            parts.append(str(value))

    walk(dict(metadata))
    return " ".join(parts)


def haystack(item: MemoryItem) -> str:
    """Case-folded content plus metadata values. Same idea as the in-memory fake."""
    parts = [item.content]
    parts.extend(str(value) for value in item.metadata.values())
    return "\n".join(parts).casefold()


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or a unix timestamp. None when it is not a time."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def redact_secrets(text: str) -> str:
    """Replace known secret env values. Memory does not import the models package."""
    redacted = text
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "AGENTMEMORY_SECRET",
    ):
        value = os.environ.get(name, "")
        if len(value) >= 4:
            redacted = redacted.replace(value, f"${name}")
    return redacted
