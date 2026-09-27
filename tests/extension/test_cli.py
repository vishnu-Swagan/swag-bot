"""``swag extension`` command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.extension.ids import DEV_EXTENSION_ID, HOST_NAME
from tests.cli_output import visible

runner = CliRunner()


def test_extension_help() -> None:
    result = runner.invoke(app, ["extension", "--help"])
    assert result.exit_code == 0
    text = visible(result)
    assert "install" in text
    assert "remove" in text
    assert "status" in text


def test_install_rejects_a_bad_extension_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("swag_bot.extension.cli.os_home", lambda: tmp_path / "home")
    monkeypatch.setattr("swag_bot.extension.cli.swag_home", lambda: tmp_path / "swag")
    result = runner.invoke(app, ["extension", "install", "--extension-id", "nope"])
    assert result.exit_code == 1
    assert "extension id" in visible(result)
    assert not (tmp_path / "home").exists()


def test_install_status_and_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    swag = tmp_path / "swag"
    monkeypatch.setattr("swag_bot.extension.cli.os_home", lambda: home)
    monkeypatch.setattr("swag_bot.extension.cli.swag_home", lambda: swag)
    monkeypatch.setattr("swag_bot.extension.cli.current_platform", lambda: "linux")
    monkeypatch.setattr("swag_bot.extension.cli.current_environ", lambda: {})
    monkeypatch.setattr("swag_bot.extension.cli.sys_executable", lambda: "/usr/bin/python3")
    installed = runner.invoke(app, ["extension", "install", "--browser", "chrome"])
    assert installed.exit_code == 0, visible(installed)
    manifest = home / ".config" / "google-chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["allowed_origins"] == [f"chrome-extension://{DEV_EXTENSION_ID}/"]
    status = runner.invoke(app, ["extension", "status"])
    assert status.exit_code == 0
    assert "host: installed" in visible(status)
    removed = runner.invoke(app, ["extension", "remove", "--browser", "chrome"])
    assert removed.exit_code == 0
    assert not manifest.exists()
    missing = runner.invoke(app, ["extension", "status"])
    assert "host: not installed" in visible(missing)
    assert "swag extension install" in visible(missing)
