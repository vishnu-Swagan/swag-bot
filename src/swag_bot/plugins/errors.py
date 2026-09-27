"""Errors raised by the plugin loader, installer, and marketplace parser."""

from __future__ import annotations

from swag_bot.errors import SwagError


class PluginError(SwagError):
    """A plugin, skill, command, or marketplace could not be loaded or installed."""
