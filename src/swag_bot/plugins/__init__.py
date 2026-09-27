"""Cowork / Claude Code compatible plugins, Agent Skills, and slash commands.

Owned by the plugins agent. See ``README.md`` in this directory and
``docs/PLUGINS.md``.
"""

from __future__ import annotations

from swag_bot.plugins.catalog import build_registry, discover_plugins
from swag_bot.plugins.cli import app, skill_app
from swag_bot.plugins.loader import load_plugin

__all__ = [
    "app",
    "build_registry",
    "discover_plugins",
    "load_plugin",
    "skill_app",
]
