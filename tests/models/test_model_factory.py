"""Factory selection for model providers."""

from __future__ import annotations

import pytest

from swag_bot.config import ModelSettings, Settings
from swag_bot.errors import ConfigError
from swag_bot.interfaces import LLMClient
from swag_bot.models import get_llm_client
from swag_bot.models.factory import split_provider_model
from swag_bot.models.litellm_client import LiteLLMClient
from swag_bot.models.ollama import OllamaClient


def test_default_is_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    client = get_llm_client(Settings())
    assert isinstance(client, OllamaClient)
    assert isinstance(client, LLMClient)
    assert client.model == "llama3.2"
    assert client.base_url == "http://127.0.0.1:11434"


def test_api_base_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.internal:11434")
    client = get_llm_client(Settings())
    assert isinstance(client, OllamaClient)
    assert client.base_url == "http://ollama.internal:11434"
    configured = get_llm_client(
        Settings(model=ModelSettings(provider="ollama", model="qwen2.5", api_base="http://10.0.0.2:11434"))
    )
    assert isinstance(configured, OllamaClient)
    assert configured.base_url == "http://10.0.0.2:11434"
    assert configured.model == "qwen2.5"


def test_cloud_providers_use_litellm() -> None:
    for provider, model in (
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-3-5-sonnet"),
        ("gemini", "gemini-2.0-flash"),
        ("openrouter", "anthropic/claude-3.5-sonnet"),
        ("litellm", "openai/gpt-4o-mini"),
    ):
        client = get_llm_client(Settings(model=ModelSettings(provider=provider, model=model)))
        assert isinstance(client, LiteLLMClient)
        assert client.provider == provider
        assert client.model == model


def test_timeout_from_settings_overrides_the_client_default() -> None:
    client = get_llm_client(Settings())
    assert isinstance(client, OllamaClient)
    assert client.timeout == 120
    slower = get_llm_client(
        Settings(model=ModelSettings(provider="ollama", model="qwen2.5:7b", timeout=600))
    )
    assert isinstance(slower, OllamaClient)
    assert slower.timeout == 600


def test_unknown_provider() -> None:
    with pytest.raises(ConfigError, match="unknown model provider"):
        get_llm_client(Settings(model=ModelSettings(provider="made-up", model="x")))


def test_split_provider_model() -> None:
    assert split_provider_model("Ollama/Llama3.2") == ("ollama", "Llama3.2")
    assert split_provider_model("openrouter/anthropic/claude-3.5-sonnet") == (
        "openrouter",
        "anthropic/claude-3.5-sonnet",
    )
    with pytest.raises(ConfigError):
        split_provider_model("llama3.2")
    with pytest.raises(ConfigError):
        split_provider_model("nope/model")
