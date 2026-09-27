"""Errors raised by model clients. These stay inside ``swag_bot.models``."""

from __future__ import annotations

from swag_bot.errors import SwagError


class ModelError(SwagError):
    """The configured model provider failed or is not usable."""


class ToolCallingUnsupported(ModelError):
    """The provider rejected a native tool-calling request.

    Callers retry with the JSON-in-text protocol instead of surfacing this
    when a tool list was supplied.
    """
