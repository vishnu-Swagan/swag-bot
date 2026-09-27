"""Adapt an ``MCPClient`` to the shared ``ToolRegistry``."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from swag_bot.interfaces import MCPClient, Tool, ToolCall


class MCPToolRegistry:
    """Tools discovered from MCP servers.

    ``register`` is not supported: the server owns the tool list.
    ``call`` delegates to ``MCPClient.call_tool``, which applies the
    permission policy.
    """

    def __init__(self, client: MCPClient) -> None:
        self._client = client

    def register(self, tool: Tool, handler: Callable[..., Any]) -> None:
        raise NotImplementedError("MCP tools come from the server")

    def get(self, name: str) -> Tool:
        for tool in self._client.list_tools():
            if tool.name == name:
                return tool
        raise KeyError(name)

    def list_tools(self) -> Sequence[Tool]:
        return self._client.list_tools()

    def call(self, tool_call: ToolCall) -> str:
        return self._client.call_tool(tool_call.name, tool_call.arguments)


def compensation_annotation(tool: Tool) -> dict[str, Any] | None:
    """Return the ``swagCompensation`` object on ``tool``, if the server sent one.

    MCP tool metadata is copied onto ``Tool.annotations``. A declaration looks
    like ``{"tool": "server__create_issue", "inverse": "server__close_issue"}``.
    The undo ledger turns that into a compensating action. This module does
    not import the safety package; it only reads the annotation.
    """
    raw = tool.annotations.get("swagCompensation")
    if isinstance(raw, dict):
        return dict(raw)
    return None
