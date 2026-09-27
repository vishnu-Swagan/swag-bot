"""``.mcp.json`` parsing and environment substitution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.errors import SwagError
from swag_bot.mcp.config import (
    load_mcp_servers,
    parse_mcp_document,
    resolve_server_spec,
    save_mcp_servers,
    substitute_env,
)


def test_substitute_env_defaults() -> None:
    env = {"NAME": "ada", "EMPTY": ""}
    assert substitute_env("hi ${NAME}", env) == "hi ada"
    assert substitute_env("${MISSING}", env) == ""
    assert substitute_env("${MISSING:-fallback}", env) == "fallback"
    assert substitute_env("${EMPTY:-fallback}", env) == "fallback"
    assert substitute_env("${EMPTY-fallback}", env) == ""
    assert substitute_env("${MISSING-fallback}", env) == "fallback"


def test_parse_claude_mcp_json_shape() -> None:
    document = {
        "mcpServers": {
            "local": {
                "command": "python",
                "args": ["server.py", "${WORKSPACE:-.}"],
                "env": {"API_TOKEN": "${API_TOKEN}"},
            },
            "remote": {
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer ${API_TOKEN}"},
            },
        }
    }
    servers = parse_mcp_document(document)
    assert servers["local"].transport == "stdio"
    assert servers["local"].args == ["server.py", "${WORKSPACE:-.}"]
    assert servers["remote"].transport == "http"
    assert servers["remote"].headers["Authorization"] == "Bearer ${API_TOKEN}"
    resolved = resolve_server_spec(
        servers["local"], {"WORKSPACE": "/work", "API_TOKEN": "secret-token"}
    )
    assert resolved.args[-1] == "/work"
    assert resolved.env["API_TOKEN"] == "secret-token"
    # The stored spec is still unsubstituted.
    assert servers["local"].env["API_TOKEN"] == "${API_TOKEN}"


def test_roundtrip_keeps_placeholders(tmp_path: Path) -> None:
    servers = parse_mcp_document(
        {
            "mcpServers": {
                "demo": {"command": "echo", "args": ["${MSG:-hi}"], "env": {"TOK": "${TOK}"}},
            }
        }
    )
    path = save_mcp_servers(servers, tmp_path / "mcp.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["mcpServers"]["demo"]["args"] == ["${MSG:-hi}"]
    assert raw["mcpServers"]["demo"]["env"]["TOK"] == "${TOK}"
    loaded = load_mcp_servers(path)
    assert loaded["demo"].command == "echo"
    assert "type" not in raw["mcpServers"]["demo"]


def test_bad_document_raises() -> None:
    with pytest.raises(SwagError):
        parse_mcp_document({"mcpServers": {"demo": "nope"}})
