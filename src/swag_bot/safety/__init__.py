"""Permissions, autonomy, the action log, and the sandbox.

Owned by the safety and MCP agent, together with ``swag_bot.mcp``.
See ``README.md`` in this directory and ``docs/SAFETY.md``.
"""

from __future__ import annotations

from pathlib import Path

from swag_bot.config import Settings
from swag_bot.interfaces import ApprovalPrompter, PermissionPolicy, Sandbox
from swag_bot.safety.cli import app
from swag_bot.safety.log import ActionLog, authorize, default_action_log_path
from swag_bot.safety.policy import DefaultPermissionPolicy, PolicyDecision, load_grants
from swag_bot.safety.prompter import RichApprovalPrompter
from swag_bot.safety.sandbox import (
    DisabledSandbox,
    DockerSandbox,
    LocalSandbox,
    docker_backend,
    make_sandbox,
)
from swag_bot.safety.taint import build_taint_tracker


def build_sandbox(settings: Settings, workdir: Path | None = None) -> Sandbox:
    """Sandbox selected by ``settings.sandbox.mode``.

    ``docker`` uses the Docker CLI when it is on ``PATH``, otherwise the
    Docker SDK when that extra is installed. If neither is available, this
    returns a ``LocalSandbox`` and emits a warning.
    """
    return make_sandbox(settings, workdir)


def build_permission_policy(settings: Settings, workdir: Path | None = None) -> PermissionPolicy:
    """Policy for ``settings.autonomy``, including grants from ``$SWAG_HOME/grants.json``.

    When the taint firewall is on, tainted sinks are escalated or denied.
    See ``docs/TAINT.md``.
    """
    taint_mode = "off"
    if settings.taint.enabled:
        taint_mode = settings.taint.mode.value
    return DefaultPermissionPolicy(
        settings.autonomy,
        grants=load_grants(),
        workdir=workdir,
        taint_mode=taint_mode,
    )


def build_prompter(settings: Settings) -> ApprovalPrompter:
    """Interactive rich approval prompt.

    ``settings`` is accepted so the factory signature matches the other
    builders. The prompt itself is always the terminal.
    """
    del settings
    return RichApprovalPrompter()


__all__ = [
    "ActionLog",
    "DisabledSandbox",
    "DockerSandbox",
    "LocalSandbox",
    "PolicyDecision",
    "app",
    "authorize",
    "build_permission_policy",
    "build_prompter",
    "build_sandbox",
    "build_taint_tracker",
    "default_action_log_path",
    "docker_backend",
]
