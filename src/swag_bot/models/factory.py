"""Select an ``LLMClient`` from settings.

``build_llm_client`` and ``get_llm_client`` select the same client.
``swag run`` calls ``build_llm_client``. ``swag model`` calls ``get_llm_client``.
"""

from __future__ import annotations

from swag_bot.config import Settings, load_settings
from swag_bot.errors import ConfigError
from swag_bot.interfaces import LLMClient
from swag_bot.models.litellm_client import LiteLLMClient
from swag_bot.models.ollama import OllamaClient

OLLAMA = "ollama"
LITELLM_PROVIDERS = frozenset({"openai", "anthropic", "gemini", "openrouter", "litellm"})
KNOWN_PROVIDERS = frozenset({OLLAMA, *LITELLM_PROVIDERS})


def get_llm_client(config: Settings | None = None) -> LLMClient:
    """Client for ``config.model``. Loads ``config.toml`` when ``config`` is omitted.

    ``ollama`` uses the native HTTP client. ``openai``, ``anthropic``,
    ``gemini``, ``openrouter``, and ``litellm`` use LiteLLM.
    """
    settings = load_settings() if config is None else config
    provider = settings.model.provider.strip().lower()
    model = settings.model.model
    api_base = settings.model.api_base
    if provider == OLLAMA:
        return OllamaClient(model=model, base_url=api_base)
    if provider in LITELLM_PROVIDERS:
        return LiteLLMClient(provider=provider, model=model, api_base=api_base)
    known = ", ".join(sorted(KNOWN_PROVIDERS))
    raise ConfigError(f"unknown model provider {provider!r}. Known providers: {known}")


def build_llm_client(settings: Settings) -> LLMClient:
    """Client for ``settings.model``. Same selection as ``get_llm_client``."""
    return get_llm_client(settings)


def split_provider_model(spec: str) -> tuple[str, str]:
    """Parse ``provider/model``. The model may itself contain slashes.

    ``openrouter/anthropic/claude-3.5-sonnet`` is provider ``openrouter`` and
    model ``anthropic/claude-3.5-sonnet``.
    """
    text = spec.strip()
    if "/" not in text:
        raise ConfigError(
            "expected provider/model, for example ollama/llama3.2 or openai/gpt-4o-mini"
        )
    provider, model = text.split("/", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        raise ConfigError(
            "expected provider/model, for example ollama/llama3.2 or openai/gpt-4o-mini"
        )
    if provider not in KNOWN_PROVIDERS:
        known = ", ".join(sorted(KNOWN_PROVIDERS))
        raise ConfigError(f"unknown model provider {provider!r}. Known providers: {known}")
    return provider, model
