"""``swag mcp`` and the body of ``swag serve-mcp``."""

from __future__ import annotations

import sys
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from swag_bot.config import load_settings
from swag_bot.errors import ConfigError, SwagError
from swag_bot.interfaces import MCPServerSpec
from swag_bot.mcp.config import load_mcp_servers, mcp_config_path, save_mcp_servers
from swag_bot.mcp.server import SkillProvider, TaskRunner

app = typer.Typer(help="MCP client and server.", no_args_is_help=True)

# Filled by the root CLI so ``swag serve-mcp`` and ``swag mcp serve`` share
# the real task runner and skill list. This module does not import core or plugins.
_task_runner: TaskRunner | None = None
_skill_provider: SkillProvider | None = None


def configure_server(
    *,
    runner: TaskRunner | None = None,
    skills_provider: SkillProvider | None = None,
) -> None:
    """Install the callables ``serve`` passes to the MCP server."""
    global _task_runner, _skill_provider
    _task_runner = runner
    _skill_provider = skills_provider


def _rewrite_mcp_help(text: str) -> str:
    """Show the MCP file for this process, not a hardcoded ``~/.swag`` path."""
    return text.replace("~/.swag/mcp.json", str(mcp_config_path()))


class _HomeAwareMcpCommand(typer.core.TyperCommand):
    """Help text that follows ``SWAG_HOME`` at the moment help is shown."""

    def __getattribute__(self, name: str) -> Any:
        value = super().__getattribute__(name)
        if name in {"help", "short_help"} and isinstance(value, str):
            return _rewrite_mcp_help(value)
        return value


def _console() -> Console:
    return Console(no_color=True, soft_wrap=True)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    http: bool = False,
) -> None:
    """Expose Swag Bot as an MCP server.

    Stdio is the default. Pass ``http=True`` for streamable HTTP on
    ``host:port``. The root ``swag serve-mcp`` command forwards ``host``,
    ``port``, and whether HTTP was requested.
    """
    try:
        from swag_bot.mcp.server import build_swag_mcp_server

        server = build_swag_mcp_server(runner=_task_runner, skills_provider=_skill_provider)
    except SwagError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(code=2) from exc
    if http:
        server.run("streamable-http", host=host, port=port)
        return
    server.run("stdio")


@app.command("list", cls=_HomeAwareMcpCommand)
def list_servers() -> None:
    """List MCP servers saved in ``~/.swag/mcp.json``."""
    console = _console()
    try:
        servers = load_mcp_servers()
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if not servers:
        console.print("No MCP servers configured.")
        return
    table = Table(title="MCP servers", show_header=True, header_style="bold")
    table.add_column("name")
    table.add_column("transport")
    table.add_column("target")
    for name, spec in servers.items():
        target = spec.command or spec.url or ""
        if spec.args:
            target = f"{target} {' '.join(spec.args)}".strip()
        table.add_row(name, spec.transport, target)
    console.print(table)


@app.command("tools")
def list_tools(
    server: Annotated[
        str | None,
        typer.Argument(help="Only this server. Omit for every server."),
    ] = None,
) -> None:
    """List tools from configured MCP servers."""
    console = _console()
    try:
        settings = load_settings()
        from swag_bot.mcp.client import build_client

        client = build_client(settings)
        tools = client.list_tools()
        client.close()
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    if server is not None:
        prefix = f"{server}__"
        tools = [tool for tool in tools if tool.name.startswith(prefix) or tool.name == server]
        if not tools and not any(spec.name == server for spec in _safe_servers()):
            console.print(f"No MCP server named {server}.")
            raise typer.Exit(code=1)
    if not tools:
        console.print("No MCP tools.")
        return
    table = Table(title="MCP tools", show_header=True, header_style="bold")
    table.add_column("name")
    table.add_column("description")
    for tool in tools:
        table.add_row(tool.name, tool.description)
    console.print(table)


@app.command("add", cls=_HomeAwareMcpCommand)
def add_server(
    name: Annotated[str, typer.Argument(help="Server name.")],
    command: Annotated[str | None, typer.Option("--command", help="Stdio executable.")] = None,
    arg: Annotated[
        list[str] | None,
        typer.Option("--arg", help="One argument. Repeat to add more."),
    ] = None,
    env: Annotated[
        list[str] | None,
        typer.Option("--env", help="KEY=VALUE. Repeat to add more."),
    ] = None,
    url: Annotated[str | None, typer.Option("--url", help="Streamable HTTP endpoint.")] = None,
    header: Annotated[
        list[str] | None,
        typer.Option("--header", help="Key=Value for HTTP. Repeat to add more."),
    ] = None,
    transport: Annotated[
        str,
        typer.Option("--transport", help="stdio or http. Default follows command vs url."),
    ] = "",
) -> None:
    """Add or replace a server in ``~/.swag/mcp.json``."""
    console = _console()
    if not name.strip():
        console.print("server name must not be empty")
        raise typer.Exit(code=1)
    if not command and not url:
        console.print("pass --command or --url")
        raise typer.Exit(code=1)
    try:
        env_map = _pairs(env or [], label="env")
        headers = _pairs(header or [], label="header")
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    chosen = transport.strip().lower()
    if not chosen:
        chosen = "http" if url and not command else "stdio"
    if chosen in {"streamable-http", "streamable_http"}:
        chosen = "http"
    spec = MCPServerSpec(
        name=name,
        command=command,
        args=list(arg or []),
        env=env_map,
        url=url,
        headers=headers,
        transport=chosen,
    )
    try:
        servers = load_mcp_servers()
        servers[name] = spec
        path = save_mcp_servers(servers)
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"saved {name} to {path}")


@app.command("remove", cls=_HomeAwareMcpCommand)
def remove_server(
    name: Annotated[str, typer.Argument(help="Server name.")],
) -> None:
    """Remove a server from ``~/.swag/mcp.json``."""
    console = _console()
    try:
        servers = load_mcp_servers()
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if name not in servers:
        console.print(f"No MCP server named {name}.")
        raise typer.Exit(code=1)
    del servers[name]
    path = save_mcp_servers(servers)
    console.print(f"removed {name} from {path}")


def _pairs(items: list[str], *, label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SwagError(f"{label} entry must be KEY=VALUE: {item}")
        key, value = item.split("=", 1)
        if not key.strip():
            raise SwagError(f"{label} key must not be empty")
        parsed[key.strip()] = value
    return parsed


def _safe_servers() -> list[MCPServerSpec]:
    try:
        return list(load_mcp_servers().values())
    except SwagError:
        return []


app.command("serve")(serve)
