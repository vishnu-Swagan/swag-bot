"""Doctor readiness names the real model and the setup command."""

from __future__ import annotations

from swag_bot.config import Settings
from swag_bot.onboarding.detect import BYOK_CANDIDATES, EnvironmentSnapshot
from swag_bot.onboarding.setup import save_model
from swag_bot.onboarding.status import doctor_report


def _keys(**overrides: bool) -> dict[str, bool]:
    keys = {env_var: False for _provider, env_var, _model in BYOK_CANDIDATES}
    keys.update(overrides)
    return keys


def _snapshot(**overrides: object) -> EnvironmentSnapshot:
    base: dict[str, object] = {
        "keys": _keys(),
        "google_api_key_set": False,
        "ollama_installed": True,
        "ollama_models": ["qwen2.5:7b"],
        "mem_bytes": 8 * 1024 * 1024 * 1024,
    }
    base.update(overrides)
    return EnvironmentSnapshot(**base)  # type: ignore[arg-type]


def test_unconfigured_status_names_the_detected_model_and_setup_command() -> None:
    report = doctor_report(settings=Settings(), snapshot=_snapshot())
    assert report["ready"] is False
    assert report["config_present"] is False
    assert "llama3.2 is not installed" not in report["reason"]
    assert "qwen2.5:7b" in report["reason"]
    assert "swag setup --auto" in report["reason"]
    assert report["detected_model"] == "qwen2.5:7b"
    assert report["detected_provider"] == "ollama"
    assert "No config file yet" in report["reason"]


def test_configured_missing_model_keeps_the_name_and_adds_the_command() -> None:
    save_model("ollama", "llama3.2")
    report = doctor_report(snapshot=_snapshot())
    assert report["ready"] is False
    assert report["config_present"] is True
    assert "llama3.2 is not installed" in report["reason"]
    assert "qwen2.5:7b" in report["reason"]
    assert "`swag setup --auto`" in report["reason"]
    assert report["detected_model"] == "qwen2.5:7b"


def test_pull_needed_names_the_exact_setup_commands() -> None:
    report = doctor_report(settings=Settings(), snapshot=_snapshot(ollama_models=[]))
    assert report["ready"] is False
    assert "qwen2.5:7b" in report["reason"]
    assert "`swag setup --auto`" in report["reason"]
    assert "`swag setup --auto --yes`" in report["reason"]
    assert "llama3.2 is not installed" not in report["reason"]


def test_ready_model_does_not_ask_for_setup() -> None:
    settings = Settings().model_copy(
        update={"model": Settings().model.model_copy(update={"model": "qwen2.5:7b"})}
    )
    report = doctor_report(settings=settings, snapshot=_snapshot())
    assert report["ready"] is True
    assert report["reason"] == "Ollama has qwen2.5:7b."
    assert "detected_model" not in report
    assert "swag setup --auto" not in report["reason"]
