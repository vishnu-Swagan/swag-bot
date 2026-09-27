"""Expose Swag Bot as an MCP server.

``runner`` and ``skills_provider`` are injected so this module does not
import the core loop or the plugin loader.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from swag_bot import __version__
from swag_bot.errors import SwagError

TaskRunner = Callable[[str], str]
SkillProvider = Callable[[], Sequence[Any]]


def build_swag_mcp_server(
    *,
    runner: TaskRunner | None = None,
    skills_provider: SkillProvider | None = None,
) -> Any:
    """MCP server with ``swag_run_task`` and ``swag_list_skills``.

    Raises ``SwagError`` when the optional ``mcp`` package is not installed.
    """
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise SwagError(
            "The optional mcp package is not installed. "
            "Install it with: pip install 'swag-bot[mcp]'"
        ) from exc

    server = MCPServer(
        "swag-bot",
        instructions="Run a Swag Bot task or list Agent Skills.",
        version=__version__,
    )

    @server.tool(description="Run a Swag Bot task. Pass the goal; the result is a short summary.")
    def swag_run_task(goal: str) -> str:
        """Run a Swag Bot task and return a short summary."""
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")
        if runner is None:
            return "No task runner is configured."
        summary = runner(goal)
        if isinstance(summary, str):
            return summary
        return json.dumps(summary)

    @server.tool(description="List Agent Skills (name and description).")
    def swag_list_skills() -> str:
        """List Agent Skills as a JSON array of name and description."""
        if skills_provider is None:
            return "[]"
        return json.dumps([_skill_row(item) for item in skills_provider()])

    return server


def _skill_row(item: Any) -> dict[str, str]:
    if isinstance(item, dict):
        return {
            "name": str(item.get("name", "")),
            "description": str(item.get("description", "")),
        }
    meta = getattr(item, "meta", None)
    if meta is not None:
        return {
            "name": str(getattr(meta, "name", "")),
            "description": str(getattr(meta, "description", "")),
        }
    return {
        "name": str(getattr(item, "name", "")),
        "description": str(getattr(item, "description", "")),
    }
