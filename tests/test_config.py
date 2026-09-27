"""Config file loading."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from swag_bot import __version__
from swag_bot.config import (
    SandboxMode,
    Settings,
    config_path,
    load_settings,
    save_settings,
    swag_home,
)
from swag_bot.errors import ConfigError
from swag_bot.interfaces import AutonomyLevel


def test_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.toml")
    assert settings.autonomy is AutonomyLevel.ASK_RISKY
    assert settings.model.provider == "ollama"
    assert settings.model.model == "llama3.2"
    assert settings.memory.backend == "memory"
    assert settings.sandbox.mode is SandboxMode.LOCAL
    assert settings.plugin_dirs == []


def test_swag_home_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SWAG_HOME", str(tmp_path))
    assert swag_home() == tmp_path
    assert config_path() == tmp_path / "config.toml"


def test_empty_swag_home_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SWAG_HOME", "  ")
    monkeypatch.setattr("swag_bot.config.Path.home", lambda: tmp_path)
    assert swag_home() == tmp_path / ".swag"


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    settings = Settings(
        autonomy=AutonomyLevel.AUTO,
        plugin_dirs=["/opt/plugins"],
        model={"provider": "openai", "model": "gpt-4o", "api_base": "https://example.test/v1"},  # type: ignore[arg-type]
        sandbox={"mode": "docker", "image": "python:3.12-slim", "network": False},  # type: ignore[arg-type]
    )
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.autonomy is AutonomyLevel.AUTO
    assert loaded.plugin_dirs == ["/opt/plugins"]
    assert loaded.model.provider == "openai"
    assert loaded.model.api_base == "https://example.test/v1"
    assert loaded.sandbox.mode is SandboxMode.DOCKER
    assert loaded.memory.path is None
    text = path.read_text(encoding="utf-8")
    assert "null" not in text


def test_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("this is = not [ valid", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_memory_mode_defaults_and_rejects_unknown(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "missing.toml").memory.mode == "auto"
    path = tmp_path / "config.toml"
    path.write_text('[memory]\nmode = "ask"\n', encoding="utf-8")
    assert load_settings(path).memory.mode == "ask"
    path.write_text('[memory]\nmode = "sometimes"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="memory.mode"):
        load_settings(path)


def test_harness_settings_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    settings = Settings()
    settings.model.harness = "tiny"
    settings.model.timeout = 90
    settings.model.fallback.provider = "ollama"
    settings.model.fallback.model = "qwen2.5:7b"
    settings.model.budget.max_escalations = 2
    settings.model.budget.max_cost_usd = 0.05
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.model.harness == "tiny"
    assert loaded.model.timeout == 90
    assert loaded.model.fallback.model == "qwen2.5:7b"
    assert loaded.model.budget.max_escalations == 2
    assert loaded.model.budget.max_cost_usd == 0.05
    assert "null" not in path.read_text(encoding="utf-8")


def test_bad_harness_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[model]\nharness = "yolo"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_bad_autonomy(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('autonomy = "yolo"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)
