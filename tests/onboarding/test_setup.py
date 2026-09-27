"""``swag setup --auto`` writes config only after a real yes, and never pulls on first run."""

from __future__ import annotations

import pytest

from swag_bot.config import config_path, load_settings
from swag_bot.onboarding.detect import BYOK_CANDIDATES, EnvironmentSnapshot
from swag_bot.onboarding.setup import first_run_if_needed, setup_auto


def _snapshot(**overrides: object) -> EnvironmentSnapshot:
    keys = {env_var: False for _provider, env_var, _model in BYOK_CANDIDATES}
    base: dict[str, object] = {
        "keys": keys,
        "google_api_key_set": False,
        "ollama_installed": True,
        "ollama_models": [],
        "mem_bytes": 8 * 1024 * 1024 * 1024,
    }
    base.update(overrides)
    return EnvironmentSnapshot(**base)  # type: ignore[arg-type]


def test_byok_writes_provider_and_not_the_key() -> None:
    keys = {env_var: False for _provider, env_var, _model in BYOK_CANDIDATES}
    keys["OPENAI_API_KEY"] = True
    result = setup_auto(snapshot=_snapshot(keys=keys, ollama_models=None))
    assert result.exit_code == 0
    assert result.wrote_config is True
    assert result.pulled is False
    settings = load_settings()
    assert settings.model.provider == "openai"
    assert settings.model.model == "gpt-4o-mini"
    text = config_path().read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in text
    assert "secret-value" not in text


def test_pull_waits_for_yes_and_dry_run_writes_nothing() -> None:
    asked: list[str] = []
    pulled: list[str] = []

    def ask(question: str) -> bool:
        asked.append(question)
        return False

    def pull(name: str, progress: object) -> None:
        del progress
        pulled.append(name)

    refused = setup_auto(snapshot=_snapshot(), interactive=True, ask=ask, pull=pull)
    assert refused.exit_code == 2
    assert refused.pulled is False
    assert pulled == []
    assert "4.7 GB" in asked[0]
    assert not config_path().is_file()

    dry = setup_auto(snapshot=_snapshot(), dry_run=True, pull=pull)
    assert dry.exit_code == 0
    assert dry.message.startswith("Dry run.")
    assert pulled == []
    assert not config_path().is_file()

    agreed = setup_auto(snapshot=_snapshot(), assume_yes=True, pull=pull)
    assert agreed.pulled is True
    assert pulled == ["qwen2.5:7b"]
    assert load_settings().model.model == "qwen2.5:7b"


def test_first_run_never_pulls(monkeypatch: pytest.MonkeyPatch) -> None:
    pulled: list[str] = []
    monkeypatch.setattr(
        "swag_bot.onboarding.setup.capture_environment",
        lambda **_kwargs: _snapshot(),
    )

    def pull(name: str, on_progress: object = None) -> None:
        del on_progress
        pulled.append(name)

    monkeypatch.setattr("swag_bot.onboarding.setup.pull_ollama_model", pull)
    notes: list[str] = []
    first_run_if_needed(announce=notes.append)
    assert pulled == []
    assert notes == []
    assert not config_path().is_file()
