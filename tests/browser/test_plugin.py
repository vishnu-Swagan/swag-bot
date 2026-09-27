"""The browser plugin installs through the normal plugin flow."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from swag_bot.browser.catalog import TOOLS, permissions_requested
from swag_bot.cli import app
from swag_bot.plugins.loader import load_plugin
from swag_bot.plugins.selector import select_skills
from swag_bot.safety.policy import grants_path, load_grants

ROOT = Path(__file__).resolve().parents[2] / "plugins" / "browser"
runner = CliRunner()


def test_plugin_validates_and_selects_the_skill() -> None:
    plugin = load_plugin(ROOT)
    manifest = plugin.manifest
    assert manifest.name == "browser"
    assert manifest.permissions == permissions_requested()
    assert {tool.permission for tool in TOOLS.values()} <= set(manifest.permissions)

    servers = plugin.list_mcp_servers()
    assert len(servers) == 1
    assert servers[0].name == "browser"
    assert servers[0].plugin == "browser"
    assert servers[0].command == "swag"
    assert servers[0].args == ["browser-mcp"]

    skill = plugin.load_skill("web-browse")
    body = skill.instructions()
    assert "browser__navigate" in body
    assert "browser__submit" in body
    assert "browser__download" in body
    assert "references/browser-workflow.md" in skill.resources()

    chosen = select_skills(
        plugin.list_skills(),
        "browse the website and extract the price",
    )
    assert [item.name for item in chosen] == ["web-browse"]

    validated = runner.invoke(app, ["plugin", "validate", str(ROOT)])
    assert validated.exit_code == 0
    assert "valid plugin browser" in validated.output


def test_install_persists_grants_and_decline_does_not(tmp_path: Path) -> None:
    del tmp_path
    installed = runner.invoke(app, ["plugin", "install", str(ROOT), "--yes"])
    assert installed.exit_code == 0
    assert "network" in installed.output
    assert "filesystem.write" in installed.output
    document = json.loads(grants_path().read_text(encoding="utf-8"))
    assert document["plugins"]["browser"] == ["filesystem.write", "mcp", "network"]
    assert load_grants()["browser"] == {"filesystem.write", "mcp", "network"}


def test_declined_install_writes_no_grants(tmp_path: Path) -> None:
    del tmp_path
    denied = runner.invoke(app, ["plugin", "install", str(ROOT)], input="n\n")
    assert denied.exit_code == 1
    assert not grants_path().exists()
    assert load_grants() == {}
