"""Model detection: a cloud key, a 7B local model, or a pull that waits for yes."""

from __future__ import annotations

from swag_bot.models.keys import PROVIDER_ENV_VARS
from swag_bot.onboarding.detect import (
    BYOK_CANDIDATES,
    RECOMMENDED_MODEL,
    EnvironmentSnapshot,
    choose_installed,
    decide,
    fetch_ollama_models,
    model_is_installed,
    parameter_billions,
)


def _snapshot(**overrides: object) -> EnvironmentSnapshot:
    keys = {env_var: False for _provider, env_var, _model in BYOK_CANDIDATES}
    base: dict[str, object] = {
        "keys": keys,
        "google_api_key_set": False,
        "ollama_installed": False,
        "ollama_models": None,
        "mem_bytes": 8 * 1024 * 1024 * 1024,
    }
    base.update(overrides)
    return EnvironmentSnapshot(**base)  # type: ignore[arg-type]


def test_byok_names_match_the_client() -> None:
    assert {env_var for _provider, env_var, _model in BYOK_CANDIDATES} == {
        env_var for _provider, env_var in PROVIDER_ENV_VARS
    }


def test_parameter_sizes() -> None:
    assert parameter_billions("qwen2.5:7b") == 7
    assert parameter_billions("llama3.2:3b") == 3
    assert parameter_billions("qwen2.5:14b") == 14
    assert parameter_billions("mxbai-embed-large") is None


def test_three_b_is_not_ready_and_qwen_7b_is_preferred() -> None:
    assert choose_installed(["llama3.2:3b"]) is None
    assert choose_installed(["qwen2.5:7b", "llama3.1:70b"]) == "qwen2.5:7b"
    assert choose_installed(["llama3.1:8b", "qwen2.5:14b"]) == "llama3.1:8b"
    assert model_is_installed("llama3.2", ["llama3.2:latest"]) is True


def test_cloud_key_wins_over_ollama() -> None:
    keys = {env_var: False for _provider, env_var, _model in BYOK_CANDIDATES}
    keys["OPENAI_API_KEY"] = True
    keys["ANTHROPIC_API_KEY"] = True
    decision = decide(_snapshot(keys=keys, ollama_models=["qwen2.5:7b"]))
    assert decision.action == "configure"
    assert decision.provider == "anthropic"
    assert "ANTHROPIC_API_KEY" in decision.message
    assert "sk-" not in decision.message


def test_running_ollama_without_a_7b_offers_the_recommended_pull() -> None:
    decision = decide(_snapshot(ollama_installed=True, ollama_models=["llama3.2:3b"]))
    assert decision.action == "pull"
    assert decision.model == RECOMMENDED_MODEL
    assert "4.7 GB" in decision.message
    assert "3B" in decision.message


def test_low_memory_does_not_offer_a_pull() -> None:
    decision = decide(
        _snapshot(ollama_models=[], mem_bytes=2 * 1024 * 1024 * 1024, google_api_key_set=True)
    )
    assert decision.action == "offer"
    assert "6 GB" in decision.message
    assert "GEMINI_API_KEY" in decision.message
    assert decision.model != RECOMMENDED_MODEL


def test_missing_ollama_tells_the_user_where_to_install_it() -> None:
    decision = decide(_snapshot())
    assert decision.action == "offer"
    assert "https://ollama.com/download" in decision.message
    assert "does not install" in decision.message


def test_daemon_probe_fails_closed_when_nothing_is_listening() -> None:
    assert fetch_ollama_models(timeout=0.2) is None
