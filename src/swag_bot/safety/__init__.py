"""Permissions, autonomy, the action log, and the sandbox.

Owned by the safety and MCP agent, together with ``swag_bot.mcp``.
See ``README.md`` in this directory.
"""

from __future__ import annotations

from swag_bot.config import Settings
from swag_bot.errors import NotImplementedYet
from swag_bot.interfaces import ApprovalPrompter, PermissionPolicy, Sandbox
from swag_bot.safety.cli import app


def build_sandbox(settings: Settings) -> Sandbox:
    """Sandbox selected by ``settings.sandbox.mode``. Stub."""
    raise NotImplementedYet("safety.build_sandbox")


def build_permission_policy(settings: Settings) -> PermissionPolicy:
    """Policy for ``settings.autonomy``. Stub."""
    raise NotImplementedYet("safety.build_permission_policy")


def build_prompter(settings: Settings) -> ApprovalPrompter:
    """Interactive approval prompt. Stub."""
    raise NotImplementedYet("safety.build_prompter")


__all__ = [
    "app",
    "build_permission_policy",
    "build_prompter",
    "build_sandbox",
]
