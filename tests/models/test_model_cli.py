"""``swag model`` CLI. Ollama is stubbed so the suite never opens a socket."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.config import load_settings
from swag_bot.models.cli import render_provider_report
from swag_bot.models.errors import ModelError
from swag_bot.models.keys import key_status

runner = CliRunner()

_SECRETS = {
    "OPENAI_API_KEY": "sk-test-openai-secret",
    "ANTHROPIC_API_KEY": "sk-ant-test-secret",
    "GEMINI_API_KEY": "gem-test-secret",
    "OPENROUTER_API_KEY": "or-test-secret",
}


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "swag_bot.models.cli.OllamaClient.list_models",
        lambda self, timeout=1.0: ["llama3.2:latest"],
    )


def test_key_status_reports_presence_not_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _SECRETS.items():
        monkeypatch.setenv(name, value)
    report = key_status()
    assert ("openai", "OPENAI_API_KEY", True) in report
    assert ("gemini", "GEMINI_API_KEY", True) in report
    rendered = render_provider_report()
    for value in _SECRETS.values():
        assert value not in rendered
    assert "OPENAI_API_KEY=set" in rendered
    assert "llama3.2:latest" in rendered
    assert "API keys are read from the environment and are not displayed." in rendered


def test_unset_keys_and_unreachable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SECRETS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "swag_bot.models.cli.OllamaClient.list_models",
        lambda self, timeout=1.0: None,
    )
    result = runner.invoke(app, ["model", "list"])
    assert result.exit_code == 0
    text = result.output
    assert "OPENAI_API_KEY=unset" in text
    assert "ANTHROPIC_API_KEY=unset" in text
    assert "models: unreachable" in text
    assert "active: ollama/llama3.2" in text


def test_model_set_persists_provider_and_model() -> None:
    result = runner.invoke(app, ["model", "set", "openrouter/anthropic/claude-3.5-sonnet"])
    assert result.exit_code == 0
    settings = load_settings()
    assert settings.model.provider == "openrouter"
    assert settings.model.model == "anthropic/claude-3.5-sonnet"
    assert settings.autonomy.value == "ask-risky"
    bad = runner.invoke(app, ["model", "set", "nope"])
    assert bad.exit_code == 1


def test_model_test_sends_one_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    class Scripted:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, prompt: str, *, model: str | None = None) -> str:
            self.prompts.append(prompt)
            return "ok"

    scripted = Scripted()
    monkeypatch.setattr("swag_bot.models.cli.get_llm_client", lambda config: scripted)
    result = runner.invoke(app, ["model", "test"])
    assert result.exit_code == 0
    assert result.output.strip() == "ok"
    assert scripted.prompts == ["Reply with the single word: ok"]


def test_model_test_redacts_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-secret")

    def boom(config: object) -> object:
        raise ModelError("provider said sk-test-openai-secret")

    monkeypatch.setattr("swag_bot.models.cli.get_llm_client", boom)
    result = runner.invoke(app, ["model", "test", "hi"])
    assert result.exit_code == 1
    assert "sk-test-openai-secret" not in result.output
    assert "$OPENAI_API_KEY" in result.output
