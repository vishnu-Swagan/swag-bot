"""Install links match the files an MCP client actually reads."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import unquote

from swag_bot.onboarding.clients import (
    claude_mcp_add_command,
    claude_plugin_mcp_json,
    cursor_install_link,
    desktop_pyproject,
    gemini_extension_manifest,
    marketplace_manifest,
    mcpb_manifest,
    stdio_server_config,
    vscode_install_link,
)
from swag_bot.plugins.loader import load_plugin
from swag_bot.plugins.marketplace import load_marketplace

ROOT = Path(__file__).resolve().parents[2]


def test_committed_manifests_match_the_generators() -> None:
    marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
    assert marketplace == marketplace_manifest()
    mcp_json = json.loads((ROOT / "plugins" / "swag-bot" / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_json == claude_plugin_mcp_json()
    gemini = json.loads((ROOT / "gemini-extension.json").read_text(encoding="utf-8"))
    assert gemini == gemini_extension_manifest()
    manifest_path = ROOT / "packaging" / "mcpb" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == mcpb_manifest()
    assert manifest["manifest_version"] == "0.4"
    assert manifest["server"]["type"] == "uv"
    pyproject = (ROOT / "packaging" / "mcpb" / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject == desktop_pyproject()


def test_claude_command_and_links_decode_to_the_stdio_server() -> None:
    command = claude_mcp_add_command()
    assert command.startswith("claude mcp add --transport stdio swag -- uvx ")
    config = stdio_server_config()
    encoded = cursor_install_link().split("config=", 1)[1]
    decoded = json.loads(base64.b64decode(unquote(encoded)))
    assert decoded == config
    vscode = json.loads(unquote(vscode_install_link().split("?", 1)[1]))
    assert vscode["name"] == "swag"
    assert vscode["command"] == config["command"]
    assert vscode["args"] == config["args"]


def test_docs_include_the_claude_one_liner() -> None:
    command = claude_mcp_add_command()
    for relative in ("README.md", "llms.txt", "docs/INSTALL_FOR_AGENTS.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert command in text
        assert "qwen2.5:7b" in text


def test_plugin_and_marketplace_load() -> None:
    loaded = load_plugin(ROOT / "plugins" / "swag-bot")
    skills = loaded.list_skills()
    assert [skill.name for skill in skills] == ["delegate-to-swag"]
    servers = loaded.list_mcp_servers()
    assert servers[0].name == "swag"
    assert servers[0].command == "uvx"
    market = load_marketplace(ROOT)
    assert market.plugins[0].name == "swag-bot"
    assert market.plugins[0].source == "./plugins/swag-bot"
