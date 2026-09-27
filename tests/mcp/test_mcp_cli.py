"""``swag mcp`` commands that do not start a server."""

from __future__ import annotations

from typer.testing import CliRunner

from swag_bot.cli import app

runner = CliRunner()


def test_mcp_add_list_remove() -> None:
    added = runner.invoke(
        app,
        [
            "mcp",
            "add",
            "demo",
            "--command",
            "python",
            "--arg",
            "server.py",
            "--env",
            "API_TOKEN=${API_TOKEN}",
        ],
    )
    assert added.exit_code == 0, added.output
    listed = runner.invoke(app, ["mcp", "list"])
    assert listed.exit_code == 0
    assert "demo" in listed.output
    assert "python" in listed.output
    assert "API_TOKEN" not in listed.output
    removed = runner.invoke(app, ["mcp", "remove", "demo"])
    assert removed.exit_code == 0
    again = runner.invoke(app, ["mcp", "list"])
    assert "demo" not in again.output
    missing = runner.invoke(app, ["mcp", "remove", "demo"])
    assert missing.exit_code == 1


def test_mcp_add_http_and_tools_when_empty() -> None:
    added = runner.invoke(
        app,
        [
            "mcp",
            "add",
            "remote",
            "--url",
            "https://example.com/mcp",
            "--transport",
            "http",
            "--header",
            "Authorization=Bearer ${API_TOKEN}",
        ],
    )
    assert added.exit_code == 0, added.output
    listed = runner.invoke(app, ["mcp", "list"])
    assert "remote" in listed.output
    assert "https://example.com/mcp" in listed.output
    assert "Bearer" not in listed.output
    # Drop it before `tools` tries to connect.
    assert runner.invoke(app, ["mcp", "remove", "remote"]).exit_code == 0
    tools = runner.invoke(app, ["mcp", "tools"])
    assert tools.exit_code == 0
    assert "No MCP tools" in tools.output


def test_mcp_help_lists_commands() -> None:
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    for name in ("list", "tools", "add", "remove", "serve"):
        assert name in result.output


def test_packages_do_not_import_each_other() -> None:
    import re
    from pathlib import Path

    root = Path("src/swag_bot")
    banned = ("swag_bot.core", "swag_bot.plugins", "swag_bot.models", "swag_bot.memory")
    for package, extra in (("safety", "swag_bot.mcp"), ("mcp", "swag_bot.safety")):
        for path in (root / package).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in (*banned, extra):
                imported = re.search(
                    rf"^\s*(?:from|import)\s+{re.escape(name)}\b",
                    text,
                    re.M,
                )
                assert imported is None, f"{path} imports {name}"
