"""``swag setup``, ``swag doctor --json``, and ``swag install-mcp``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.onboarding.clients import claude_mcp_add_command, cursor_install_link

runner = CliRunner()


def test_setup_dry_run_does_not_write_config(_isolated_swag_home: Path) -> None:
    result = runner.invoke(app, ["setup", "--auto", "--dry-run"])
    text = result.output
    assert result.exit_code == 0, text
    assert "Dry run." in text
    assert "https://ollama.com/download" in text
    assert not (_isolated_swag_home / "config.toml").is_file()


def test_doctor_json_has_ready_and_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-value")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ready"] is False
    assert payload["autonomy"] == "ask-risky"
    assert "super-secret-value" not in result.output
    assert "reason" in payload


def test_grant_dry_run_does_not_write(_isolated_swag_home: Path) -> None:
    result = runner.invoke(app, ["setup", "--grant", "write", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Would preapprove: write" in result.output
    assert not (_isolated_swag_home / "mcp-approvals.json").is_file()


def test_grant_persists(_isolated_swag_home: Path) -> None:
    result = runner.invoke(app, ["setup", "--grant", "write"])
    assert result.exit_code == 0, result.output
    stored = json.loads((_isolated_swag_home / "mcp-approvals.json").read_text(encoding="utf-8"))
    assert stored["risks"] == ["write"]


def test_install_mcp_prints_verified_commands() -> None:
    result = runner.invoke(app, ["install-mcp", "--client", "claude"])
    assert result.exit_code == 0, result.output
    assert claude_mcp_add_command() in result.output
    cursor = runner.invoke(app, ["install-mcp", "--client", "cursor"])
    assert cursor_install_link() in cursor.output
    unknown = runner.invoke(app, ["install-mcp", "--client", "nope"])
    assert unknown.exit_code == 1
