"""Pluggable memory store.

Owned by the models and memory agent, together with ``swag_bot.models``.
See ``README.md`` in this directory.
"""

from __future__ import annotations

from swag_bot.config import Settings
from swag_bot.errors import NotImplementedYet
from swag_bot.interfaces import MemoryStore
from swag_bot.memory.cli import app


def build_memory_store(settings: Settings) -> MemoryStore:
    """Store selected by ``settings.memory.backend``. Stub."""
    raise NotImplementedYet("memory.build_memory_store")


__all__ = ["app", "build_memory_store"]
