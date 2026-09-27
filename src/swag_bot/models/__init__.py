"""LLM clients: LiteLLM, Ollama, and bring-your-own-key providers.

Owned by the models and memory agent, together with ``swag_bot.memory``.
See ``README.md`` in this directory.
"""

from __future__ import annotations

from swag_bot.config import Settings
from swag_bot.errors import NotImplementedYet
from swag_bot.interfaces import LLMClient
from swag_bot.models.cli import app


def build_llm_client(settings: Settings) -> LLMClient:
    """Client for ``settings.model``. Stub."""
    raise NotImplementedYet("models.build_llm_client")


__all__ = ["app", "build_llm_client"]
