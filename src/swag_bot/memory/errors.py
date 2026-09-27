"""Errors raised by memory backends. These stay inside ``swag_bot.memory``."""

from __future__ import annotations

from swag_bot.errors import SwagError


class MemoryError(SwagError):
    """The configured memory backend failed."""
