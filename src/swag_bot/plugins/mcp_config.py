"""Parse ``.mcp.json`` and inline ``mcpServers`` maps into ``MCPServerSpec`` values.

This module does not start servers, expand environment variables, or read
secret values. ``${VAR}`` references stay literal for the MCP client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swag_bot.interfaces import MCPServerSpec
from swag_bot.plugins.errors import PluginError

_TRANSPORTS = {"stdio": "stdio", "http": "http", "sse": "sse", "ws": "ws"}
_TRANSPORT_ALIASES = {
    "streamable-http": "http",
    "http-stream": "http",
    "websocket": "ws",
}


def load_mcp_file(path: Path) -> list[MCPServerSpec]:
    """Load a JSON file. Accepts ``{"mcpServers": {...}}`` or a bare name-to-spec map."""
    data = _read_json_object(path)
    if "mcpServers" in data:
        servers = data["mcpServers"]
        if not isinstance(servers, dict):
            raise PluginError(f"{path}: mcpServers must be an object")
        return parse_mcp_map(servers, path=path)
    return parse_mcp_map(data, path=path)


def parse_mcp_map(servers: dict[str, Any], *, path: Path | None = None) -> list[MCPServerSpec]:
    """Turn an ``mcpServers`` object into specs. Order follows the JSON object."""
    where = f"{path}: " if path is not None else ""
    specs: list[MCPServerSpec] = []
    for name, raw in servers.items():
        if not isinstance(name, str) or not name.strip():
            raise PluginError(f"{where}MCP server name must be a non-empty string")
        if not isinstance(raw, dict):
            raise PluginError(f"{where}MCP server {name!r} must be an object")
        specs.append(_one_server(name, raw, where))
    return specs


def _one_server(name: str, raw: dict[str, Any], where: str) -> MCPServerSpec:
    command = raw.get("command")
    url = raw.get("url")
    if command is not None and not isinstance(command, str):
        raise PluginError(f"{where}MCP server {name!r} command must be a string")
    if url is not None and not isinstance(url, str):
        raise PluginError(f"{where}MCP server {name!r} url must be a string")
    args_raw = raw.get("args", [])
    if args_raw is None:
        args_raw = []
    if not isinstance(args_raw, list) or not all(isinstance(item, str) for item in args_raw):
        raise PluginError(f"{where}MCP server {name!r} args must be a list of strings")
    env_raw = raw.get("env", {})
    if env_raw is None:
        env_raw = {}
    if not isinstance(env_raw, dict):
        raise PluginError(f"{where}MCP server {name!r} env must be an object")
    env = _string_map(env_raw, name=name, where=where, field="env")
    headers_raw = raw.get("headers", {})
    if headers_raw is None:
        headers_raw = {}
    if not isinstance(headers_raw, dict):
        raise PluginError(f"{where}MCP server {name!r} headers must be an object")
    headers = _string_map(headers_raw, name=name, where=where, field="headers")
    transport = _transport(raw.get("transport") or raw.get("type"), command, url, name, where)
    return MCPServerSpec(
        name=name,
        command=command,
        args=list(args_raw),
        env=env,
        url=url,
        headers=headers,
        transport=transport,
    )


def _string_map(
    raw: dict[Any, Any],
    *,
    name: str,
    where: str,
    field: str,
) -> dict[str, str]:
    """Copy a string map. Non-strings are rejected so secrets stay as ``${VAR}`` refs."""
    parsed: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise PluginError(f"{where}MCP server {name!r} {field} keys must be strings")
        if not isinstance(value, str):
            raise PluginError(
                f"{where}MCP server {name!r} {field} values must be strings "
                "(use an environment-variable reference, not a literal secret)"
            )
        parsed[key] = value
    return parsed


def _transport(declared: Any, command: str | None, url: str | None, name: str, where: str) -> str:
    if declared is not None:
        if not isinstance(declared, str):
            raise PluginError(f"{where}MCP server {name!r} transport must be a string")
        key = declared.strip().lower()
        if key in _TRANSPORTS:
            return _TRANSPORTS[key]
        if key in _TRANSPORT_ALIASES:
            return _TRANSPORT_ALIASES[key]
        raise PluginError(f"{where}MCP server {name!r} has unknown transport {declared!r}")
    if command:
        return "stdio"
    if url:
        return "http"
    raise PluginError(f"{where}MCP server {name!r} needs a command or a url")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PluginError(f"{path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PluginError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise PluginError(f"{path}: JSON value must be an object")
    return data
