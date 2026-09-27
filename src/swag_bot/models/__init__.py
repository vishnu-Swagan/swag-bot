"""LLM clients: LiteLLM, Ollama, and bring-your-own-key providers.

Owned by the models and memory agent, together with ``swag_bot.memory``.
See ``README.md`` in this directory and ``docs/MODELS.md``.
"""

from __future__ import annotations

from swag_bot.models.cli import app
from swag_bot.models.factory import build_llm_client, get_llm_client
from swag_bot.models.litellm_client import LiteLLMClient
from swag_bot.models.ollama import OllamaClient

__all__ = [
    "LiteLLMClient",
    "OllamaClient",
    "app",
    "build_llm_client",
    "get_llm_client",
]
