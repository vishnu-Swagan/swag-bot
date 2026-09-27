"""``swag safety`` commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from swag_bot.config import load_settings
from swag_bot.errors import ConfigError, SwagError
from swag_bot.interfaces import RiskLevel, default_requires_approval
from swag_bot.safety.log import ActionLog, default_action_log_path
from swag_bot.safety.policy import change_grant, grants_path, load_grants, load_suspended_grants

app = typer.Typer(
    help="Permissions, autonomy, and the action log.",
    no_args_is_help=True,
)


def _console() -> Console:
    return Console(no_color=True, soft_wrap=True, width=120)


@app.command("log")
def show_log(
    limit: Annotated[int, typer.Option(help="Show only the last N entries.")] = 0,
    path: Annotated[
        str,
        typer.Option(help="JSONL file. Default is $SWAG_HOME/actions.jsonl."),
    ] = "",
) -> None:
    """Print the append-only action log."""
    console = _console()
    target = default_action_log_path() if not path else Path(path)
    try:
        entries = ActionLog(target).read()
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if limit > 0:
        entries = entries[-limit:]
    if not entries:
        console.print("No actions logged.")
        return
    table = Table(title="action log", show_header=True, header_style="bold")
    for column in ("time", "kind", "risk", "summary", "approved", "approver"):
        table.add_column(column)
    for entry in entries:
        table.add_row(
            entry.timestamp.isoformat(timespec="seconds"),
            entry.action.kind,
            entry.action.risk.value,
            entry.action.summary,
            "yes" if entry.approved else "no",
            entry.approver,
        )
    console.print(table)


@app.command("policy")
def show_policy() -> None:
    """Print the autonomy level, risk rules, and plugin grants."""
    console = _console()
    try:
        settings = load_settings()
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    autonomy = settings.autonomy
    console.print(f"autonomy: {autonomy.value}")
    console.print("ask-always: prompt for every action, including reads")
    console.print("ask-risky: prompt unless the risk is read")
    console.print("auto: do not prompt; still log every action; a hard deny still applies")
    console.print("")
    console.print("Risky actions (prompted at ask-risky):")
    console.print("- file write, including a write that leaves the workdir")
    console.print("- shell commands")
    console.print("- network, and sending messages")
    console.print("- spending money, and deleting")
    console.print("- unknown permission names")
    console.print("A destructive risk is never lowered.")
    console.print("Writes outside the workdir are destructive.")
    taint = settings.taint
    firewall = "on" if taint.enabled and taint.mode.value != "off" else "off"
    console.print("")
    console.print(
        f"taint firewall: {firewall} "
        f"(mode={taint.mode.value}, reader={taint.reader.value}, "
        f"workspace={taint.workspace.value}, memory={taint.memory.value})"
    )
    console.print(
        "Untrusted data (web pages, MCP results, plugin output, files outside the "
        "workspace) cannot by itself drive network, destructive, credential, or send "
        "actions. escalate asks and shows the source; block denies; auto denies "
        "because it cannot ask. See docs/TAINT.md."
    )
    console.print("")
    table = Table(title=f"prompts at {autonomy.value}", show_header=True, header_style="bold")
    table.add_column("risk")
    table.add_column("prompt")
    for risk in RiskLevel:
        prompted = default_requires_approval(autonomy, risk)
        table.add_row(risk.value, "yes" if prompted else "no")
    console.print(table)
    console.print("")
    try:
        grants = load_grants()
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if not grants:
        console.print(f"plugin grants: (none) ({grants_path()})")
    else:
        _print_grant_table(console, "plugin grants", grants)
    try:
        suspended = load_suspended_grants()
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if suspended:
        console.print("")
        console.print("Suspended grants are not applied while the plugin is disabled.")
        _print_grant_table(console, "suspended grants", suspended)


@app.command("grant")
def grant_permission(
    plugin: Annotated[str, typer.Argument(help="Plugin name.")],
    permission: Annotated[
        str,
        typer.Argument(help="Permission to grant, such as filesystem.read."),
    ],
) -> None:
    """Grant one permission to a plugin."""
    _mutate_grant(plugin, permission, add=True)


@app.command("revoke")
def revoke_permission(
    plugin: Annotated[str, typer.Argument(help="Plugin name.")],
    permission: Annotated[str, typer.Argument(help="Permission to remove.")],
) -> None:
    """Remove one permission from a plugin."""
    _mutate_grant(plugin, permission, add=False)


def _mutate_grant(plugin: str, permission: str, *, add: bool) -> None:
    console = _console()
    if not plugin.strip() or not permission.strip() or any(ch.isspace() for ch in permission):
        console.print("plugin and permission must be non-empty and contain no spaces")
        raise typer.Exit(code=1)
    try:
        change_grant(plugin, permission, add=add)
    except SwagError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    verb = "granted" if add else "revoked"
    console.print(f"{verb} {permission} for {plugin}")


def _print_grant_table(console: Console, title: str, grants: dict[str, set[str]]) -> None:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("plugin")
    table.add_column("permissions")
    for name, permissions in sorted(grants.items()):
        table.add_row(name, ", ".join(sorted(permissions)))
    console.print(table)
