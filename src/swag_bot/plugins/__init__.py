"""Cowork / Claude Code compatible plugins, Agent Skills, and slash commands.

Owned by the plugins agent. See ``README.md`` in this directory.
"""

from __future__ import annotations

from pathlib import Path

from swag_bot.config import Settings
from swag_bot.errors import NotImplementedYet
from swag_bot.interfaces import Plugin
from swag_bot.plugins.cli import app


def discover_plugins(settings: Settings) -> list[Plugin]:
    """Plugins from ``settings.plugin_dirs`` and the default layout. Stub."""
    raise NotImplementedYet("plugins.discover_plugins")


def load_plugin(root: Path) -> Plugin:
    """Load one plugin directory. Stub."""
    raise NotImplementedYet("plugins.load_plugin")


__all__ = ["app", "discover_plugins", "load_plugin"]
