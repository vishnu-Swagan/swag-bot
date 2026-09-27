"""Marketplace manifests and installing one entry from a local catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.installer import install_plugin
from swag_bot.plugins.marketplace import load_marketplace, select_entry
from tests.plugins.helpers import write_plugin


def _marketplace(root: Path, plugins: list[dict[str, object]], **extra: object) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "name": "demo-market",
        "owner": {"name": "Ada"},
        "plugins": plugins,
    }
    payload.update(extra)
    manifest = root / ".claude-plugin"
    manifest.mkdir(parents=True, exist_ok=True)
    (manifest / "marketplace.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_parse_marketplace_sources(tmp_path: Path) -> None:
    root = _marketplace(
        tmp_path / "market",
        [
            {
                "name": "local-plugin",
                "source": "./plugins/local-plugin",
                "description": "Local",
                "version": "1.2.0",
            },
            {
                "name": "remote-plugin",
                "source": {"source": "github", "repo": "acme/tools", "ref": "v1"},
                "description": "Remote",
            },
            {
                "name": "git-plugin",
                "source": {
                    "source": "url",
                    "url": "https://example.com/plugin.git",
                    "ref": "main",
                },
            },
        ],
        metadata={"pluginRoot": "./plugins"},
    )
    market = load_marketplace(root)
    assert market.name == "demo-market"
    assert market.owner.name == "Ada"
    assert market.plugin_root == "./plugins"
    assert market.plugins[0].source == "./plugins/local-plugin"
    assert market.plugins[1].source == {"source": "github", "repo": "acme/tools", "ref": "v1"}
    assert market.plugins[2].source["source"] == "url"
    with pytest.raises(PluginError, match="more than one plugin"):
        select_entry(market, None)
    assert select_entry(market, "remote-plugin").name == "remote-plugin"


def test_malformed_marketplace(tmp_path: Path) -> None:
    root = tmp_path / "market"
    manifest = root / ".claude-plugin"
    manifest.mkdir(parents=True)
    (manifest / "marketplace.json").write_text("{", encoding="utf-8")
    with pytest.raises(PluginError, match="invalid JSON"):
        load_marketplace(root)

    (manifest / "marketplace.json").write_text(
        json.dumps({"name": "demo-market", "owner": {"name": "Ada"}}),
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="invalid marketplace"):
        load_marketplace(root)

    (manifest / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "demo-market",
                "owner": {"name": "Ada"},
                "plugins": [
                    {"name": "same", "source": "./a"},
                    {"name": "same", "source": "./b"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="unique"):
        load_marketplace(root)


def test_install_relative_marketplace_plugin(tmp_path: Path) -> None:
    market = tmp_path / "market"
    write_plugin(
        market / "plugins" / "demo-plugin",
        permissions=["mcp"],
        description="Installed from a marketplace.",
    )
    _marketplace(
        market,
        [
            {
                "name": "demo-plugin",
                "source": "demo-plugin",
                "description": "Installed from a marketplace.",
            }
        ],
        metadata={"pluginRoot": "./plugins"},
    )
    home = tmp_path / "home"
    record = install_plugin(str(market), assume_yes=True, home=home)
    assert record.name == "demo-plugin"
    assert record.permissions == ["mcp"]
    assert (home / "plugins" / "demo-plugin" / "skills" / "demo-skill" / "SKILL.md").is_file()


def test_marketplace_path_escape(tmp_path: Path) -> None:
    market = _marketplace(
        tmp_path / "market",
        [{"name": "demo-plugin", "source": "../outside"}],
    )
    write_plugin(tmp_path / "outside")
    with pytest.raises(PluginError, match="escapes"):
        install_plugin(str(market), assume_yes=True, home=tmp_path / "home")


def test_marketplace_github_source_clones(tmp_path: Path) -> None:
    market = _marketplace(
        tmp_path / "market",
        [
            {
                "name": "from-github",
                "source": {"source": "github", "repo": "acme/helper", "ref": "v2"},
            }
        ],
    )
    seen: list[tuple[str, str | None]] = []

    def fake_clone(url: str, dest: Path, ref: str | None) -> None:
        seen.append((url, ref))
        write_plugin(dest, name="from-github", permissions=["network"])

    record = install_plugin(
        str(market),
        assume_yes=True,
        home=tmp_path / "home",
        clone=fake_clone,
        plugin_name="from-github",
    )
    assert seen == [("https://github.com/acme/helper.git", "v2")]
    assert record.name == "from-github"


def test_npm_source_is_refused(tmp_path: Path) -> None:
    market = _marketplace(
        tmp_path / "market",
        [{"name": "pkg", "source": {"source": "npm", "package": "@example/plugin"}}],
    )
    with pytest.raises(PluginError, match="npm"):
        install_plugin(str(market), assume_yes=True, home=tmp_path / "home")


def test_strict_false_without_plugin_json(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "market" / "plugins" / "loose"
    skill = plugin_dir / "skills" / "loose-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: loose-skill\n"
        "description: A loose skill from a marketplace entry.\n"
        "---\n\n"
        "Body\n",
        encoding="utf-8",
    )
    _marketplace(
        tmp_path / "market",
        [
            {
                "name": "loose",
                "source": "./plugins/loose",
                "description": "No plugin.json",
                "version": "0.0.1",
                "strict": False,
                "permissions": ["filesystem.read"],
            }
        ],
    )
    record = install_plugin(str(tmp_path / "market"), assume_yes=True, home=tmp_path / "home")
    assert record.name == "loose"
    assert record.permissions == ["filesystem.read"]
    assert record.version == "0.0.1"
