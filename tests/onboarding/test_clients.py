"""Install links match the files an MCP client actually reads."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import unquote

from swag_bot import __version__
from swag_bot.onboarding.clients import (
    claude_marketplace_commands,
    claude_mcp_add_command,
    claude_plugin_mcp_json,
    codex_mcp_add_command,
    cursor_install_link,
    desktop_pyproject,
    gemini_extension_manifest,
    gemini_install_command,
    marketplace_manifest,
    mcpb_manifest,
    stdio_server_config,
    uvx_setup_auto_command,
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


def test_plugin_and_manifests_match_the_package_version() -> None:
    plugin = json.loads(
        (ROOT / "plugins" / "swag-bot" / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert plugin["version"] == __version__
    loaded = load_plugin(ROOT / "plugins" / "swag-bot")
    for skill in loaded.list_skills():
        assert skill.metadata.get("version") == __version__
    gemini = json.loads((ROOT / "gemini-extension.json").read_text(encoding="utf-8"))
    assert gemini["version"] == __version__
    manifest_path = ROOT / "packaging" / "mcpb" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == __version__


def test_install_prompts_use_generated_commands_and_name_the_reload() -> None:
    text = (ROOT / "docs" / "INSTALL_FOR_AGENTS.md").read_text(encoding="utf-8")
    short, reference = text.split("## Reference prompt", 1)
    assert "THE TASK" not in short
    assert "THE TASK" in reference
    assert uvx_setup_auto_command() in short
    assert claude_mcp_add_command() in text
    marketplace, install = claude_marketplace_commands()
    assert marketplace in short
    assert install in short
    assert "/reload-plugins --force" in short
    assert cursor_install_link() in short
    assert vscode_install_link() in short
    assert gemini_install_command() in short
    assert codex_mcp_add_command() in short
    assert "npx @anthropic-ai/mcpb pack packaging/mcpb swag-bot.mcpb" in short
    assert "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0" in text
    assert "swag_start_task" in text
    skill = (
        ROOT / "plugins" / "swag-bot" / "skills" / "delegate-to-swag" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "swag_start_task" in skill
    assert "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0" in skill
    assert "/reload-plugins --force" in text


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
