"""``~/.swag/mcp.json`` and Claude Code ``.mcp.json`` server entries.

Values may contain ``${VAR}``, ``${VAR:-default}``, and ``${VAR-default}``.
Substitution happens when a client connects, not when the file is saved, so
``swag mcp list`` does not expand secrets.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from swag_bot.config import swag_home
from swag_bot.errors import SwagError
from swag_bot.interfaces import MCPServerSpec

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|-)([^}]*))?\}")

_HTTP_TRANSPORTS = {"http", "streamable-http", "streamable_http"}
_STDIO = "stdio"


def mcp_config_path() -> Path:
    """User MCP server file for this ``SWAG_HOME``."""
    return swag_home() / "mcp.json"


def substitute_env(value: str, env: Mapping[str, str] | None = None) -> str:
    """Expand ``${VAR}``, ``${VAR:-default}`` (unset or empty), and ``${VAR-default}`` (unset)."""
    source = os.environ if env is None else env

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        operator = match.group(2)
        default = match.group(3) or ""
        if name in source:
            current = source[name]
            if current == "" and operator == ":-":
                return default
            return current
        if operator is not None:
            return default
        return ""

    return _ENV_PATTERN.sub(repl, value)


def substitute_mapping(
    values: Mapping[str, str], env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Substitute environment placeholders in each value."""
    return {key: substitute_env(item, env) for key, item in values.items()}


def effective_transport(spec: MCPServerSpec) -> str:
    """``stdio`` or ``http``. Other names are returned so the caller can reject them."""
    transport = (spec.transport or _STDIO).strip().lower()
    if transport in _HTTP_TRANSPORTS:
        return "http"
    if transport in {"", _STDIO} and spec.url and not spec.command:
        return "http"
    if transport == _STDIO:
        return _STDIO
    return transport


def resolve_server_spec(spec: MCPServerSpec, env: Mapping[str, str] | None = None) -> MCPServerSpec:
    """Return a copy with environment placeholders expanded."""
    command = substitute_env(spec.command, env) if spec.command else None
    url = substitute_env(spec.url, env) if spec.url else None
    return spec.model_copy(
        update={
            "command": command,
            "args": [substitute_env(item, env) for item in spec.args],
            "env": substitute_mapping(spec.env, env),
            "url": url,
            "headers": substitute_mapping(spec.headers, env),
        }
    )


def parse_mcp_document(data: Mapping[str, Any]) -> dict[str, MCPServerSpec]:
    """Parse a Claude Code ``.mcp.json`` object or a bare ``mcpServers`` map."""
    if "mcpServers" in data:
        raw_servers = data["mcpServers"]
    else:
        raw_servers = data
    if not isinstance(raw_servers, dict):
        raise SwagError("mcp.json mcpServers must be an object")
    servers: dict[str, MCPServerSpec] = {}
    for name, entry in raw_servers.items():
        if not isinstance(name, str) or not name.strip():
            raise SwagError("MCP server names must be non-empty strings")
        if not isinstance(entry, dict):
            raise SwagError(f"MCP server {name} must be an object")
        servers[name] = _spec_from_entry(name, entry)
    return servers


def load_mcp_servers(path: Path | None = None) -> dict[str, MCPServerSpec]:
    """Load servers. A missing file means there are none."""
    target = mcp_config_path() if path is None else path
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SwagError(f"cannot read {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise SwagError(f"cannot read {target}: top level must be an object")
    return parse_mcp_document(data)


def save_mcp_servers(servers: Mapping[str, MCPServerSpec], path: Path | None = None) -> Path:
    """Write servers in the ``.mcp.json`` shape. Returns the path written."""
    target = mcp_config_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mcpServers": {name: _entry_from_spec(spec) for name, spec in servers.items()}}
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def _spec_from_entry(name: str, entry: Mapping[str, Any]) -> MCPServerSpec:
    command = _optional_str(entry.get("command"))
    url = _optional_str(entry.get("url"))
    args = entry.get("args") or []
    env = entry.get("env") or {}
    headers = entry.get("headers") or {}
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise SwagError(f"MCP server {name} args must be a list of strings")
    if not _string_map(env):
        raise SwagError(f"MCP server {name} env must be a string map")
    if not _string_map(headers):
        raise SwagError(f"MCP server {name} headers must be a string map")
    transport = _optional_str(entry.get("transport")) or _optional_str(entry.get("type")) or ""
    if not transport:
        transport = "http" if url and not command else "stdio"
    transport = _normalize_transport(transport)
    return MCPServerSpec(
        name=name,
        command=command,
        args=list(args),
        env=dict(env),
        url=url,
        headers=dict(headers),
        transport=transport,
    )


def _entry_from_spec(spec: MCPServerSpec) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if spec.command:
        entry["command"] = spec.command
    if spec.args:
        entry["args"] = list(spec.args)
    if spec.env:
        entry["env"] = dict(spec.env)
    if spec.url:
        entry["url"] = spec.url
    if spec.headers:
        entry["headers"] = dict(spec.headers)
    transport = effective_transport(spec)
    if transport != "stdio":
        entry["type"] = "http" if transport == "http" else spec.transport
    return entry


def _normalize_transport(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in _HTTP_TRANSPORTS:
        return "http"
    if lowered in {"ws", "websocket"}:
        return "ws"
    return lowered or "stdio"


def _string_map(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SwagError("MCP server command, url, and transport must be strings")
    stripped = value.strip()
    return stripped or None
