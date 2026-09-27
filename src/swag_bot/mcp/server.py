"""Expose Swag Bot as an MCP server.

``runner`` and ``skills_provider`` are injected so this module does not
import the core loop or the plugin loader. Tool registration, including
elicitation for approvals, lives in ``swag_bot.onboarding.mcp_bridge``.
"""

from __future__ import annotations

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
    """MCP server for tasks, skills, and setup status.

    Raises ``SwagError`` when the optional ``mcp`` package is not installed.
    Approvals are routed through MCP elicitation or a preapproved grant.
    The server does not read stdin or write prompts to stdout.
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
        instructions=(
            "Run a Swag Bot task or list Agent Skills. "
            "Write and shell actions ask with MCP elicitation when you support it. "
            "Otherwise they are denied unless the user preapproved them."
        ),
        version=__version__,
    )
    from swag_bot.onboarding.mcp_bridge import register_tools

    register_tools(server, runner=runner, skills_provider=skills_provider)
    return server
