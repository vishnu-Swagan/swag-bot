"""Local OpenAI-compatible servers and the free-cloud menu.

HTTP is mocked. These tests do not open a socket and do not read a tty.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.config import Settings, config_path, load_settings
from swag_bot.errors import SwagError
from swag_bot.models.keys import redact_secrets
from swag_bot.onboarding.detect import BYOK_CANDIDATES, EnvironmentSnapshot, decide
from swag_bot.onboarding.free_cloud import FREE_PROVIDERS, menu_text
from swag_bot.onboarding.local_servers import (
    LOCAL_ENDPOINTS,
    LocalServerState,
    choose_local_model,
    first_usable_server,
    normalize_base_url,
    probe_local_servers,
    probe_openai_models,
)
from swag_bot.onboarding.probe_hook import small_model_probe_available, unknown_size_note
from swag_bot.onboarding.secrets import apply_saved_keys, save_provider_key, secrets_path
from swag_bot.onboarding.setup import setup_auto
from swag_bot.onboarding.status import doctor_report

runner = CliRunner()


def _keys(**enabled: bool) -> dict[str, bool]:
    found = {env_var: False for _provider, env_var, _model in BYOK_CANDIDATES}
    for item in FREE_PROVIDERS:
        found.setdefault(item.env_var, False)
    found.update(enabled)
    return found


def _snapshot(**overrides: object) -> EnvironmentSnapshot:
    base: dict[str, object] = {
        "keys": _keys(),
        "google_api_key_set": False,
        "ollama_installed": False,
        "ollama_models": None,
        "mem_bytes": 8 * 1024 * 1024 * 1024,
        "local_servers": (),
    }
    base.update(overrides)
    return EnvironmentSnapshot(**base)  # type: ignore[arg-type]


def _body(ids: list[str]) -> bytes:
    return json.dumps({"data": [{"id": item} for item in ids]}).encode("utf-8")


def test_each_known_local_server_is_probed_at_its_docs_url() -> None:
    assert [url for _name, url, _docs in LOCAL_ENDPOINTS] == [
        "http://localhost:1234/v1",
        "http://localhost:1337/v1",
        "http://localhost:8080/v1",
        "http://localhost:4891/v1",
    ]
    for name, url, _docs in LOCAL_ENDPOINTS:
        seen: list[str] = []

        def opener(target: str, timeout: float, *, expected: str = url) -> bytes | None:
            del timeout
            seen.append(target)
            if target == expected + "/models":
                return _body(["qwen2.5-7b-instruct"])
            return None

        found = probe_local_servers(timeout=0.1, opener=opener)
        assert [item.name for item in found] == [name]
        choice = first_usable_server(found)
        assert choice is not None
        assert choice.base_url == url
        assert choice.litellm_model == "openai/qwen2.5-7b-instruct"
        assert choice.size_known is True
        assert url + "/models" in seen


def test_server_that_does_not_answer_is_skipped() -> None:
    def opener(target: str, timeout: float) -> bytes | None:
        del target, timeout
        return None

    assert probe_local_servers(timeout=0.1, opener=opener) == []
    assert probe_openai_models("http://localhost:1234/v1", timeout=0.1, opener=opener) is None


def test_under_7b_is_skipped_and_unknown_size_is_allowed() -> None:
    assert choose_local_model(["llama3.2-3b", "tiny-1.5b"]) is None
    picked = choose_local_model(["my-local-model", "llama3.2-3b"])
    assert picked == ("my-local-model", False)
    preferred = choose_local_model(["llama3.1-8b", "qwen2.5-7b"])
    assert preferred == ("qwen2.5-7b", True)
    note = unknown_size_note("my-local-model")
    assert "my-local-model" in note
    assert "Run `swag model probe`" in note
    assert small_model_probe_available() is True


def test_local_7b_is_used_when_ollama_has_only_a_3b() -> None:
    server = LocalServerState(
        name="LM Studio",
        base_url="http://localhost:1234/v1",
        model_ids=["qwen2.5-7b"],
    )
    decision = decide(
        _snapshot(
            ollama_installed=True,
            ollama_models=["llama3.2:3b"],
            local_servers=(server,),
        )
    )
    assert decision.action == "configure"
    assert decision.provider == "litellm"
    assert decision.model == "openai/qwen2.5-7b"
    assert decision.api_base == "http://localhost:1234/v1"
    assert "this machine" in decision.message


def test_installed_ollama_7b_wins_over_a_local_server() -> None:
    server = LocalServerState(
        name="Jan",
        base_url="http://localhost:1337/v1",
        model_ids=["qwen2.5-7b"],
    )
    decision = decide(_snapshot(ollama_models=["qwen2.5:7b"], local_servers=(server,)))
    assert decision.provider == "ollama"
    assert decision.model == "qwen2.5:7b"


def test_undersized_local_server_is_named_in_the_cloud_menu() -> None:
    server = LocalServerState(
        name="GPT4All",
        base_url="http://localhost:4891/v1",
        model_ids=["llama3.2-3b"],
    )
    decision = decide(_snapshot(local_servers=(server,)))
    assert decision.action == "offer"
    assert "GPT4All" in decision.message
    assert "under 7B" in decision.message


def test_unknown_size_is_configured_and_the_note_says_so() -> None:
    server = LocalServerState(
        name="Jan",
        base_url="http://localhost:1337/v1",
        model_ids=["custom-jan"],
    )
    decision = decide(_snapshot(local_servers=(server,)))
    assert decision.action == "configure"
    assert decision.model == "openai/custom-jan"
    assert "does not say" in decision.message
    assert "swag model probe" in decision.message


def test_free_env_vars_are_detected_without_a_prompt() -> None:
    expected = {
        "GEMINI_API_KEY": ("gemini", "gemini-2.5-flash"),
        "GROQ_API_KEY": ("litellm", "groq/llama-3.3-70b-versatile"),
        "OPENROUTER_API_KEY": ("openrouter", "openrouter/free"),
        "CEREBRAS_API_KEY": ("litellm", "cerebras/gpt-oss-120b"),
        "MISTRAL_API_KEY": ("litellm", "mistral/mistral-small-latest"),
    }
    for env_var, (provider, model) in expected.items():
        decision = decide(_snapshot(keys=_keys(**{env_var: True})))
        assert decision.action == "configure"
        assert decision.provider == provider
        assert decision.model == model
        assert env_var in decision.message
    text = menu_text()
    assert "rate-limit" in text
    assert "GitHub Models was retired" in text
    assert "docs/MODELS.md" in text
    for item in FREE_PROVIDERS:
        assert item.key_url in text
        assert item.limits_url in text
    assert "requests per" not in text.lower()


def test_anthropic_still_wins_over_a_free_plan_key() -> None:
    decision = decide(_snapshot(keys=_keys(ANTHROPIC_API_KEY=True, GROQ_API_KEY=True)))
    assert decision.provider == "anthropic"


def test_offer_dry_run_and_noninteractive_never_prompt() -> None:
    calls: list[str] = []

    def choose(prompt: str) -> str:
        calls.append(prompt)
        return "groq"

    def read_secret(prompt: str) -> str:
        calls.append(prompt)
        return "gsk-should-not-be-read"

    snapshot = _snapshot()
    dry = setup_auto(
        snapshot=snapshot,
        dry_run=True,
        interactive=True,
        choose=choose,
        read_secret=read_secret,
    )
    assert dry.exit_code == 0
    assert dry.message.startswith("Dry run.")
    assert "https://console.groq.com/keys" in dry.message
    assert calls == []
    assert not config_path().is_file()

    quiet = setup_auto(
        snapshot=snapshot,
        interactive=False,
        choose=choose,
        read_secret=read_secret,
    )
    assert quiet.exit_code == 2
    assert quiet.wrote_config is False
    assert calls == []
    assert "Nothing was written." in quiet.message
    assert not secrets_path().is_file()


def test_interactive_menu_stores_a_mode_0600_key_and_hides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "gsk-test-secret-value"
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    result = setup_auto(
        snapshot=_snapshot(),
        interactive=True,
        choose=lambda _prompt: "2",
        read_secret=lambda _prompt: secret,
    )
    assert result.exit_code == 0
    assert result.provider == "litellm"
    assert result.model == "groq/llama-3.3-70b-versatile"
    assert secret not in result.message
    assert "GROQ_API_KEY" in result.message
    settings = load_settings()
    assert settings.model.provider == "litellm"
    assert settings.model.model == result.model
    assert settings.model.api_base is None
    config_text = config_path().read_text(encoding="utf-8")
    assert secret not in config_text
    assert "GROQ_API_KEY" not in config_text
    path = secrets_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert secret in path.read_text(encoding="utf-8")
    apply_saved_keys()
    assert os.environ["GROQ_API_KEY"] == secret
    monkeypatch.setenv("GROQ_API_KEY", "already-set")
    apply_saved_keys()
    assert os.environ["GROQ_API_KEY"] == "already-set"


def test_saved_key_is_redacted_from_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-secret-value")
    assert redact_secrets("upstream said gsk-test-secret-value") == "upstream said $GROQ_API_KEY"


def test_base_url_configures_litellm_and_refuses_a_dead_or_tiny_server() -> None:
    def opener(target: str, timeout: float) -> bytes | None:
        del timeout
        if target == "http://127.0.0.1:9000/v1/models":
            return _body(["custom-model"])
        return None

    dry = setup_auto(base_url="127.0.0.1:9000", dry_run=True, opener=opener)
    assert dry.exit_code == 0
    assert dry.wrote_config is False
    assert dry.model == "openai/custom-model"
    assert "does not say" in dry.message
    assert not config_path().is_file()

    saved = setup_auto(base_url="http://127.0.0.1:9000/v1/models", opener=opener)
    assert saved.exit_code == 0
    assert load_settings().model.api_base == "http://127.0.0.1:9000/v1"
    assert load_settings().model.provider == "litellm"

    def down(_target: str, _timeout: float) -> bytes | None:
        return None

    with pytest.raises(SwagError, match="answered"):
        setup_auto(base_url="http://127.0.0.1:9001/v1", opener=down)

    def tiny(target: str, timeout: float) -> bytes | None:
        del target, timeout
        return _body(["llama3.2-3b"])

    with pytest.raises(SwagError, match="under 7B"):
        setup_auto(base_url="http://localhost:1234/v1", opener=tiny)


def test_base_url_dry_run_from_the_cli(
    monkeypatch: pytest.MonkeyPatch, _isolated_swag_home: Path
) -> None:
    def fake(base: str, *, timeout: float, opener: object = None) -> list[str]:
        del base, timeout, opener
        return ["qwen2.5-7b-instruct"]

    monkeypatch.setattr("swag_bot.onboarding.local_servers.probe_openai_models", fake)
    result = runner.invoke(
        app,
        ["setup", "--auto", "--dry-run", "--base-url", "http://localhost:1234/v1"],
    )
    assert result.exit_code == 0, result.output
    assert "Dry run." in result.output
    assert "openai/qwen2.5-7b-instruct" in result.output
    assert "localhost:1234" in result.output
    assert not (_isolated_swag_home / "config.toml").is_file()


def test_doctor_is_ready_for_a_local_server_and_a_free_key() -> None:
    server = LocalServerState(
        name="LM Studio",
        base_url="http://localhost:1234/v1",
        model_ids=["qwen2.5-7b"],
    )
    settings = Settings().model_copy(
        update={
            "model": Settings().model.model_copy(
                update={
                    "provider": "litellm",
                    "model": "openai/qwen2.5-7b",
                    "api_base": "http://localhost:1234/v1",
                }
            )
        }
    )
    report = doctor_report(settings=settings, snapshot=_snapshot(local_servers=(server,)))
    assert report["ready"] is True
    assert report["api_base"] == "http://localhost:1234/v1"

    cloud = Settings().model_copy(
        update={
            "model": Settings().model.model_copy(
                update={"provider": "litellm", "model": "groq/llama-3.3-70b-versatile"}
            )
        }
    )
    missing = doctor_report(settings=cloud, snapshot=_snapshot())
    assert missing["ready"] is False
    present = doctor_report(settings=cloud, snapshot=_snapshot(keys=_keys(GROQ_API_KEY=True)))
    assert present["ready"] is True
    assert "GROQ_API_KEY" in present["reason"]


def test_normalize_base_url_appends_v1() -> None:
    assert normalize_base_url("localhost:1234") == "http://localhost:1234/v1"
    assert normalize_base_url("http://localhost:1234/v1/models") == "http://localhost:1234/v1"


def test_save_provider_key_rejects_an_unknown_name() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        save_provider_key("GITHUB_TOKEN", "ghp-nope")
