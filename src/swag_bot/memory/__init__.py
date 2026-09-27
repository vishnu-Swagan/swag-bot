"""Pluggable memory store.

Owned by the models and memory agent, together with ``swag_bot.models``.
See ``README.md`` in this directory and ``docs/MODELS.md``.
"""

from __future__ import annotations

from swag_bot.memory.agentmemory import AgentMemoryStore
from swag_bot.memory.cli import app
from swag_bot.memory.factory import build_memory_store, get_memory_store
from swag_bot.memory.json_store import JsonFileMemoryStore
from swag_bot.memory.sqlite import SQLiteMemoryStore

__all__ = [
    "AgentMemoryStore",
    "JsonFileMemoryStore",
    "SQLiteMemoryStore",
    "app",
    "build_memory_store",
    "get_memory_store",
]
