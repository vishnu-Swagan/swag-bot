"""Smoke tests for the root CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot import __version__
from swag_bot.cli import app
from tests.cli_output import visible as _visible

runner = CliRunner()

_HELP_COMMANDS = (
    "run",
    "plugin",
    "serve-mcp",
    "version",
    "doctor",
    "safety",
    "mcp",
    "model",
    "memory",
)


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in _HELP_COMMANDS:
        assert name in _visible(result)


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in _visible(result)


def test_run_help() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    text = _visible(result)
    assert "--dry-run" in text
    assert "goal" in text.lower()
    assert "\x1b" not in text


def test_plugin_help() -> None:
    result = runner.invoke(app, ["plugin", "--help"])
    assert result.exit_code == 0
    text = _visible(result)
    assert "list" in text
    assert "validate" in text


def test_serve_mcp_help() -> None:
    result = runner.invoke(app, ["serve-mcp", "--help"])
    assert result.exit_code == 0
    text = _visible(result).lower()
    assert "stdio" in text
    assert "--http" in text
    assert "\x1b" not in text


def test_doctor_reports_the_sqlite_memory_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    absent = runner.invoke(app, ["doctor"])
    absent_text = _visible(absent)
    assert absent.exit_code == 0
    assert "sqlite (config: memory)" in absent_text
    assert str(home / "memory.db") in absent_text
    assert "not created yet" in absent_text
    assert "memory.mode" in absent_text
    from swag_bot.memory.sqlite import SQLiteMemoryStore

    SQLiteMemoryStore(home / "memory.db").close()
    present = runner.invoke(app, ["doctor"])
    present_text = _visible(present)
    assert "present" in present_text
    assert "(none)" not in present_text.split("memory.path", 1)[1].split("sandbox.mode", 1)[0]


def test_doctor_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-value")
    result = runner.invoke(app, ["doctor"])
    text = _visible(result)
    assert result.exit_code == 0
    assert "super-secret-value" not in text
    assert "ask-risky" in text
    assert "ollama" in text
    assert "litellm" in text
    assert "API keys are read from the environment" in text
