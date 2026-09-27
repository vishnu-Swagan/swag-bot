"""MCP client, and the process that serves Swag Bot as an MCP server.

Owned by the safety and MCP agent, together with ``swag_bot.safety``.
See ``README.md`` in this directory.
"""

from __future__ import annotations

from swag_bot.config import Settings
from swag_bot.errors import NotImplementedYet
from swag_bot.interfaces import MCPClient
from swag_bot.mcp.cli import app


def build_mcp_client(settings: Settings) -> MCPClient:
    """Client for the MCP servers configured by plugins. Stub."""
    raise NotImplementedYet("mcp.build_mcp_client")


__all__ = ["app", "build_mcp_client"]
