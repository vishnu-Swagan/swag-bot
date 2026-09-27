"""``swag plugin`` and ``swag skill`` commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from tests.plugins.helpers import write_plugin, write_skill

runner = CliRunner()
EXAMPLE = Path(__file__).resolve().parents[2] / "plugins" / "example-github-helper"


def _visible(result: object) -> str:
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    output = getattr(result, "output", "") or ""
    return f"{stdout}\n{stderr}\n{output}"


def test_plugin_help_lists_management_commands() -> None:
    result = runner.invoke(app, ["plugin", "--help"])
    assert result.exit_code == 0
    for name in ("install", "list", "enable", "disable", "remove", "info", "show", "validate"):
        assert name in result.output


def test_validate_example_plugin() -> None:
    result = runner.invoke(app, ["plugin", "validate", str(EXAMPLE)])
    text = _visible(result)
    assert result.exit_code == 0
    assert "example-github-helper" in text
    assert "skills: 1" in text
    assert "commands: 1" in text
    assert "mcp servers: 1" in text
    assert "network" in text


def test_validate_malformed_manifest(tmp_path: Path) -> None:
    root = tmp_path / "broken"
    manifest = root / ".claude-plugin"
    manifest.mkdir(parents=True)
    (manifest / "plugin.json").write_text("{", encoding="utf-8")
    result = runner.invoke(app, ["plugin", "validate", str(root)])
    assert result.exit_code == 1
    assert "invalid JSON" in _visible(result)


def test_install_list_info_disable_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    monkeypatch.chdir(project)
    source = write_plugin(
        tmp_path / "src",
        name="demo-plugin",
        permissions=["filesystem.read", "mcp"],
        skill_description="Demo skill used in tests. Use when the user mentions demos.",
    )
    denied = runner.invoke(app, ["plugin", "install", str(source)], input="n\n")
    denied_text = _visible(denied)
    assert denied.exit_code == 1
    assert "filesystem.read" in denied_text
    assert "mcp" in denied_text
    assert "installation denied" in denied_text
    assert not (home / "plugins" / "demo-plugin").exists()

    installed = runner.invoke(app, ["plugin", "install", str(source), "--yes"])
    assert installed.exit_code == 0
    assert "filesystem.read" in _visible(installed)
    assert "installed demo-plugin" in _visible(installed)
    assert (home / "plugins" / "registry.json").is_file()

    listed = runner.invoke(app, ["plugin", "list"])
    assert listed.exit_code == 0
    assert "demo-plugin" in _visible(listed)

    info = runner.invoke(app, ["plugin", "info", "demo-plugin"])
    assert info.exit_code == 0
    info_text = _visible(info)
    assert "demo-skill" in info_text
    assert "permissions: filesystem.read, mcp" in info_text

    show = runner.invoke(app, ["plugin", "show", "demo-plugin"])
    assert show.exit_code == 0
    assert "demo-plugin" in _visible(show)

    skills = runner.invoke(app, ["skill", "list"])
    assert skills.exit_code == 0
    assert "demo-skill" in _visible(skills)

    disabled = runner.invoke(app, ["plugin", "disable", "demo-plugin"])
    assert disabled.exit_code == 0
    enabled = runner.invoke(app, ["plugin", "enable", "demo-plugin"])
    assert enabled.exit_code == 0

    write_skill(
        project / ".agents" / "skills" / "pdf-processing",
        name="pdf-processing",
        description="Extract text from PDF files. Use when the user mentions PDFs.",
    )
    write_skill(
        home / "skills" / "notes",
        name="notes",
        description="Take notes. Use when the user mentions notes.",
    )
    both = runner.invoke(app, ["skill", "list"])
    both_text = _visible(both)
    assert "pdf-processing" in both_text
    assert "notes" in both_text
    assert "demo-skill" in both_text

    removed = runner.invoke(app, ["plugin", "remove", "demo-plugin"])
    assert removed.exit_code == 0
    missing = runner.invoke(app, ["plugin", "info", "demo-plugin"])
    assert missing.exit_code == 1
    assert "not found" in _visible(missing)
