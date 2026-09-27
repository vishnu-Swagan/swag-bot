"""MCP client, and the process that serves Swag Bot as an MCP server.

Owned by the safety and MCP agent, together with ``swag_bot.safety``.
See ``README.md`` in this directory and ``docs/SAFETY.md``.
"""

from __future__ import annotations

from swag_bot.config import Settings
from swag_bot.interfaces import (
    ApprovalPrompter,
    MCPServerSpec,
    PermissionPolicy,
    TaintTracker,
)
from swag_bot.mcp.cli import app
from swag_bot.mcp.client import ActionRecorder, SessionOpener, SwagMCPClient, build_client


def build_mcp_client(
    settings: Settings,
    *,
    policy: PermissionPolicy | None = None,
    prompter: ApprovalPrompter | None = None,
    recorder: ActionRecorder | None = None,
    opener: SessionOpener | None = None,
    servers: list[MCPServerSpec] | None = None,
    taint: TaintTracker | None = None,
) -> SwagMCPClient:
    """Client for the MCP servers in ``~/.swag/mcp.json``.

    ``policy`` is asked before every tool call. When it is omitted, the
    client uses ``settings.autonomy`` and does not prompt less often than
    ``default_requires_approval``. Pass the safety policy from the
    composition root when you want plugin grants and raised risk levels.
    """
    return build_client(
        settings,
        policy=policy,
        prompter=prompter,
        recorder=recorder,
        opener=opener,
        servers=servers,
        taint=taint,
    )


__all__ = [
    "SwagMCPClient",
    "app",
    "build_mcp_client",
]
