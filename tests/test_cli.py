"""Smoke tests for the root CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from swag_bot import __version__
from swag_bot.cli import app

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
        assert name in result.output


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_run_help() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "goal" in result.output.lower()


def test_plugin_help() -> None:
    result = runner.invoke(app, ["plugin", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "validate" in result.output


def test_serve_mcp_help() -> None:
    result = runner.invoke(app, ["serve-mcp", "--help"])
    assert result.exit_code == 0
    text = _visible(result).lower()
    assert "stdio" in text
    assert "--http" in result.output


def _visible(result: object) -> str:
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    output = getattr(result, "output", "") or ""
    return f"{stdout}\n{stderr}\n{output}"


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
