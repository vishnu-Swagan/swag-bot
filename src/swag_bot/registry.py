"""Default in-memory ``ToolRegistry``.

Shared by every area. Behavior changes here affect the whole agent, so keep
them compatible: same method names, ``KeyError`` on a missing tool, string
results from ``call``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from swag_bot.interfaces import Tool, ToolCall


class InMemoryToolRegistry:
    """Dict-backed tool registry. Registering the same name replaces the old tool."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, tool: Tool, handler: Callable[..., Any]) -> None:
        if not tool.name:
            raise ValueError("tool name is required")
        self._tools[tool.name] = tool
        self._handlers[tool.name] = handler

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(name) from None

    def list_tools(self) -> Sequence[Tool]:
        return list(self._tools.values())

    def call(self, tool_call: ToolCall) -> str:
        try:
            handler = self._handlers[tool_call.name]
        except KeyError:
            raise KeyError(tool_call.name) from None
        result = handler(**tool_call.arguments)
        if isinstance(result, str):
            return result
        return json.dumps(result)


__all__ = ["InMemoryToolRegistry"]
