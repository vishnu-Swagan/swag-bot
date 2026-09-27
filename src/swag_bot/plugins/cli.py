"""``swag plugin`` and ``swag skill`` commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from swag_bot.config import load_settings, swag_home
from swag_bot.interfaces import ActionRequest
from swag_bot.plugins.catalog import build_registry, find_plugin
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.installer import (
    install_plugin,
    installed_plugin_dir,
    list_installed,
    remove_plugin,
    set_enabled,
)
from swag_bot.plugins.loader import LoadedPlugin, load_plugin, plugins_from_path

app = typer.Typer(
    help="Install and inspect Cowork-compatible plugins.",
    no_args_is_help=True,
)

skill_app = typer.Typer(
    help="Inspect Agent Skills from plugins and skill directories.",
    no_args_is_help=True,
)


class CliApprovalPrompter:
    """``ApprovalPrompter`` that prints the install request and asks on the terminal."""

    def prompt(self, action: ActionRequest) -> bool:
        _print_permissions(action)
        return typer.confirm("Allow this plugin install?", default=False)


@app.command("list")
def list_plugins() -> None:
    """List installed plugins and plugins found in plugin_dirs."""
    try:
        _print_plugin_list()
    except PluginError as exc:
        _fail(exc)


@app.command("install")
def install(
    source: Annotated[
        str,
        typer.Argument(help="Local path, git URL, or GitHub owner/repo[@ref]."),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Show permissions and install without a prompt."),
    ] = False,
    plugin_name: Annotated[
        str | None,
        typer.Option("--plugin", help="Plugin name when the source is a marketplace."),
    ] = None,
) -> None:
    """Install a plugin. Shows requested permissions and asks before copying."""
    try:
        record = install_plugin(
            source,
            prompter=CliApprovalPrompter(),
            assume_yes=yes,
            plugin_name=plugin_name,
            announce=_print_permissions if yes else None,
        )
    except PluginError as exc:
        _fail(exc)
    location = installed_plugin_dir(swag_home(), record.name)
    state = "yes" if record.enabled else "no"
    version = record.version or "unversioned"
    typer.echo(f"installed {record.name} {version} (enabled: {state})")
    typer.echo(f"location: {location}")


@app.command("enable")
def enable(
    name: Annotated[str, typer.Argument(help="Installed plugin name.")],
) -> None:
    """Enable an installed plugin."""
    try:
        record = set_enabled(name, True)
    except PluginError as exc:
        _fail(exc)
    typer.echo(f"enabled {record.name}")


@app.command("disable")
def disable(
    name: Annotated[str, typer.Argument(help="Installed plugin name.")],
) -> None:
    """Disable an installed plugin without deleting it."""
    try:
        record = set_enabled(name, False)
    except PluginError as exc:
        _fail(exc)
    typer.echo(f"disabled {record.name}")


@app.command("remove")
def remove(
    name: Annotated[str, typer.Argument(help="Installed plugin name.")],
) -> None:
    """Remove an installed plugin and its registry entry."""
    try:
        remove_plugin(name)
    except PluginError as exc:
        _fail(exc)
    typer.echo(f"removed {name}")


@app.command("info")
def info(
    name: Annotated[str, typer.Argument(help="Plugin name.")],
) -> None:
    """Show one plugin's manifest, skills, commands, agents, and MCP servers."""
    _show(name)


@app.command("show")
def show(
    name: Annotated[str, typer.Argument(help="Plugin name.")],
) -> None:
    """Show one plugin's manifest."""
    _show(name)


@app.command("validate")
def validate(
    path: Annotated[
        Path,
        typer.Argument(help="Plugin root (the directory that contains .claude-plugin/)."),
    ],
) -> None:
    """Validate a Cowork / Claude Code plugin directory."""
    try:
        plugin = load_plugin(path)
        skills = plugin.list_skills()
        commands = plugin.list_commands()
        agents = plugin.list_agents()
        servers = plugin.list_mcp_servers()
    except PluginError as exc:
        _fail(exc)
    manifest = plugin.manifest
    version = manifest.version or "unversioned"
    typer.echo(f"valid plugin {manifest.name} ({version})")
    typer.echo(f"skills: {len(skills)}")
    typer.echo(f"commands: {len(commands)}")
    typer.echo(f"agents: {len(agents)}")
    typer.echo(f"mcp servers: {len(servers)}")
    if manifest.permissions:
        typer.echo("permissions: " + ", ".join(manifest.permissions))
    else:
        typer.echo("permissions: (none)")


@skill_app.command("list")
def list_skills() -> None:
    """List skill name and description metadata. Bodies are not loaded."""
    try:
        registry = build_registry(load_settings())
        skills = registry.list_skills()
    except PluginError as exc:
        _fail(exc)
    if not skills:
        typer.echo("no skills found")
        return
    console, table = _table("skills", ["name", "description", "location"])
    for meta in skills:
        location = str(meta.location) if meta.location is not None else ""
        table.add_row(meta.name, meta.description, location)
    console.print(table)


def _show(name: str) -> None:
    try:
        settings = load_settings()
        plugin = find_plugin(name, settings)
        records = {record.name: record for record in list_installed()}
    except PluginError as exc:
        _fail(exc)
    record = records.get(name)
    _print_plugin_info(plugin, enabled=None if record is None else record.enabled)


def _print_plugin_list() -> None:
    settings = load_settings()
    records = list_installed()
    known = {record.name for record in records}
    console, table = _table("plugins", ["name", "version", "enabled", "source"])
    if not records and not settings.plugin_dirs:
        typer.echo("no plugins installed")
        return
    for record in records:
        table.add_row(
            record.name,
            record.version or "",
            "yes" if record.enabled else "no",
            record.source,
        )
    for entry in settings.plugin_dirs:
        for plugin in plugins_from_path(Path(entry)):
            if plugin.manifest.name in known:
                continue
            table.add_row(
                plugin.manifest.name,
                plugin.manifest.version or "",
                "discovered",
                str(plugin.root),
            )
    console.print(table)


def _print_plugin_info(plugin: LoadedPlugin, *, enabled: bool | None) -> None:
    manifest = plugin.manifest
    console = _console()
    console.print(f"name: {manifest.name}")
    if manifest.display_name:
        console.print(f"display name: {manifest.display_name}")
    console.print(f"version: {manifest.version or '(none)'}")
    console.print(f"description: {manifest.description or '(none)'}")
    if manifest.author is not None:
        console.print(f"author: {manifest.author.name}")
    if manifest.license:
        console.print(f"license: {manifest.license}")
    if enabled is None:
        console.print("enabled: not installed")
    else:
        console.print(f"enabled: {'yes' if enabled else 'no'}")
    console.print(f"root: {plugin.root}")
    _print_named("permissions", manifest.permissions)
    _print_named("skills", [meta.name for meta in plugin.list_skills()])
    _print_named("commands", [command.name for command in plugin.list_commands()])
    _print_named("agents", [agent.name for agent in plugin.list_agents()])
    _print_named("mcp servers", [server.name for server in plugin.list_mcp_servers()])
    for meta in plugin.list_skills():
        console.print(f"skill {meta.name}: {meta.description}")


def _print_named(label: str, names: list[str]) -> None:
    if names:
        typer.echo(f"{label}: {', '.join(names)}")
    else:
        typer.echo(f"{label}: (none)")


def _print_permissions(action: ActionRequest) -> None:
    """Show the install request once.

    ``action.summary`` already names the permissions. A second bullet list
    made the prompt repeat them.
    """
    typer.echo(action.summary)


def _console() -> Console:
    """Follow the real terminal width. A fixed width wraps twice on a narrow screen."""
    return Console(no_color=True, soft_wrap=True)


def _table(title: str, columns: list[str]) -> tuple[Console, Table]:
    console = _console()
    table = Table(title=title, show_header=True, header_style="bold")
    for column in columns:
        table.add_column(column)
    return console, table


def _fail(exc: PluginError) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc
