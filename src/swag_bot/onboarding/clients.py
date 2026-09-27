"""One-liners and install links for MCP clients.

Shapes were checked against the vendor docs on 2026-09-27:

- Claude Code: ``claude mcp add --transport stdio <name> -- <command>``
  (https://code.claude.com/docs/en/mcp). The ``--`` keeps the launcher
  arguments from being parsed as Claude flags.
- Cursor: ``cursor://anysphere.cursor-deeplink/mcp/install?name=&config=``
  with ``config`` the standard base64 of the server object, not the wrapper
  that repeats the name (https://cursor.com/docs/mcp/install-links).
- VS Code: ``vscode:mcp/install?`` plus a URL-encoded JSON object that
  includes ``name`` (https://code.visualstudio.com/api/extension-guides/ai/mcp).
- Gemini CLI: ``gemini extensions install <github-url>`` with
  ``gemini-extension.json`` ``mcpServers``
  (https://geminicli.com/docs/extensions/reference).
- Claude Desktop: MCPB manifest 0.4, server type ``uv``
  (https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md).
- Cowork uses the same plugin marketplace as Claude Code
  (https://code.claude.com/docs/en/plugin-marketplaces).
"""

from __future__ import annotations

import base64
import json
import shlex
from typing import Any
from urllib.parse import quote

from swag_bot import __version__
from swag_bot.onboarding.distribution import (
    CONSOLE_SCRIPT,
    GIT_INSTALL_URL,
    PACKAGE_NAME,
    uvx_serve_args,
)

GITHUB_REPO = "vishnu-Swagan/swag-bot"
GITHUB_URL = "https://github.com/vishnu-Swagan/swag-bot"
MARKETPLACE_NAME = "swag-bot"
PLUGIN_NAME = "swag-bot"
MCP_SERVER_NAME = "swag"
CLAUDE_ADD_FLAGS = ("claude", "mcp", "add", "--transport", "stdio", MCP_SERVER_NAME, "--", "uvx")


def stdio_server_config() -> dict[str, Any]:
    """Cursor and Claude ``mcpServers`` entry: command plus args, no name key."""
    return {"command": "uvx", "args": uvx_serve_args()}


def claude_mcp_add_command() -> str:
    """One shell command that registers Swag Bot with Claude Code."""
    parts = [*CLAUDE_ADD_FLAGS, *uvx_serve_args()]
    return " ".join(shlex.quote(part) for part in parts)


def claude_marketplace_commands() -> tuple[str, str]:
    """Register this repo as a marketplace, then install the plugin."""
    add = f"claude plugin marketplace add {GITHUB_REPO}"
    install = f"claude plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME}"
    return add, install


def cursor_install_link() -> str:
    """Cursor deeplink. ``config`` is base64 of the server object only."""
    encoded = base64.b64encode(
        json.dumps(stdio_server_config(), separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return (
        "cursor://anysphere.cursor-deeplink/mcp/install"
        f"?name={quote(MCP_SERVER_NAME, safe='')}&config={quote(encoded, safe='')}"
    )


def vscode_install_link(*, insiders: bool = False) -> str:
    """VS Code install URL. The query string is the URL-encoded JSON object."""
    payload = {"name": MCP_SERVER_NAME, **stdio_server_config()}
    scheme = "vscode-insiders" if insiders else "vscode"
    encoded = quote(json.dumps(payload, separators=(",", ":")), safe="")
    return f"{scheme}:mcp/install?{encoded}"


def vscode_add_mcp_command() -> str:
    """``code --add-mcp`` example from the VS Code user docs."""
    payload = json.dumps({"name": MCP_SERVER_NAME, **stdio_server_config()}, separators=(",", ":"))
    return "code --add-mcp " + shlex.quote(payload)


def gemini_extension_manifest() -> dict[str, Any]:
    """``gemini-extension.json`` body. ``command`` and ``args`` are separate."""
    return {
        "name": PLUGIN_NAME,
        "version": __version__,
        "description": "Hand long, checkable tasks to Swag Bot over MCP.",
        "mcpServers": {MCP_SERVER_NAME: stdio_server_config()},
    }


def gemini_install_command() -> str:
    """Install this repository as a Gemini CLI extension."""
    return f"gemini extensions install {GITHUB_URL}"


def claude_plugin_mcp_json() -> dict[str, Any]:
    """``.mcp.json`` at the Claude plugin root."""
    return {"mcpServers": {MCP_SERVER_NAME: stdio_server_config()}}


def marketplace_manifest() -> dict[str, Any]:
    """``.claude-plugin/marketplace.json`` at the repository root."""
    return {
        "name": MARKETPLACE_NAME,
        "description": "Swag Bot, a local agent you can hand a task to.",
        "owner": {"name": "Vishnu M"},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": "./plugins/swag-bot",
                "description": (
                    "MCP server and a skill that tells Claude when to delegate "
                    "a long, verifiable task to Swag Bot."
                ),
            }
        ],
    }


def mcpb_manifest() -> dict[str, Any]:
    """Claude Desktop MCPB manifest. Server type ``uv`` is manifest 0.4."""
    return {
        "manifest_version": "0.4",
        "name": PLUGIN_NAME,
        "display_name": "Swag Bot",
        "version": __version__,
        "description": "Run a Swag Bot task from Claude Desktop.",
        "author": {"name": "Vishnu M", "url": GITHUB_URL},
        "license": "MIT",
        "repository": {"type": "git", "url": f"{GITHUB_URL}.git"},
        "server": {
            "type": "uv",
            "entry_point": "src/server.py",
            "mcp_config": {
                "command": "uv",
                "args": [
                    "run",
                    "--project",
                    "${__dirname}",
                    "python",
                    "${__dirname}/src/server.py",
                ],
            },
        },
        "tools_generated": True,
        "keywords": ["agent", "swag-bot"],
        "compatibility": {
            "platforms": ["darwin", "win32", "linux"],
            "runtimes": {"python": ">=3.11"},
        },
    }


def desktop_pyproject() -> str:
    """``pyproject.toml`` the uv MCPB host installs."""
    spec = f"{PACKAGE_NAME}[mcp] @ {GIT_INSTALL_URL}" if not _pypi() else f"{PACKAGE_NAME}[mcp]"
    return (
        "[project]\n"
        'name = "swag-bot-desktop"\n'
        f'version = "{__version__}"\n'
        'description = "Claude Desktop entry point for Swag Bot."\n'
        'requires-python = ">=3.11"\n'
        "dependencies = [\n"
        f'    "{spec}",\n'
        "]\n"
    )


def chatgpt_note() -> str:
    """Honest limit: ChatGPT cannot attach a local stdio MCP server."""
    return (
        "ChatGPT needs a remote HTTPS MCP server. `swag serve-mcp --http` "
        "listens on 127.0.0.1 only, and a developer tunnel is not a supported "
        "one-prompt path. This repo does not ship a hosted relay."
    )


def render_client(name: str) -> str:
    """Plain-text instructions for one client name."""
    key = name.strip().lower()
    if key in {"claude", "claude-code", "cowork"}:
        add, install = claude_marketplace_commands()
        return "\n".join(
            [
                "Claude Code / Cowork",
                claude_mcp_add_command(),
                "Or install the plugin marketplace from this repo:",
                add,
                install,
                "Inside a session the same words work as /plugin marketplace add "
                f"{GITHUB_REPO} and /plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME}.",
            ]
        )
    if key == "cursor":
        return "\n".join(
            [
                "Cursor",
                cursor_install_link(),
                "Cursor asks before it installs the server.",
            ]
        )
    if key in {"vscode", "vs-code", "code"}:
        return "\n".join(
            [
                "VS Code",
                vscode_install_link(),
                vscode_add_mcp_command(),
            ]
        )
    if key in {"gemini", "gemini-cli"}:
        return "\n".join(["Gemini CLI", gemini_install_command()])
    if key in {"desktop", "claude-desktop"}:
        return "\n".join(
            [
                "Claude Desktop",
                "Pack packaging/mcpb with: "
                "npx @anthropic-ai/mcpb pack packaging/mcpb swag-bot.mcpb",
                "Open the .mcpb file in Claude Desktop. "
                "It reviews the extension before installing.",
                "Sign a release build with: npx @anthropic-ai/mcpb sign swag-bot.mcpb",
            ]
        )
    if key == "chatgpt":
        return "\n".join(
            [
                "ChatGPT",
                chatgpt_note(),
                "Local HTTP, for developers on this machine:",
                f"{CONSOLE_SCRIPT} serve-mcp --http",
            ]
        )
    known = "claude, cursor, vscode, gemini, desktop, chatgpt"
    raise ValueError(f"unknown MCP client {name!r}. Known clients: {known}")


def _pypi() -> bool:
    from swag_bot.onboarding.distribution import PYPI_PUBLISHED

    return PYPI_PUBLISHED
