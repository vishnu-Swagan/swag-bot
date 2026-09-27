"""``swag setup`` and ``swag install-mcp``."""

from __future__ import annotations

import getpass
import json
import sys
from typing import Annotated

import typer

from swag_bot.errors import ConfigError, SwagError
from swag_bot.onboarding.approvals import add_grant
from swag_bot.onboarding.clients import render_client
from swag_bot.onboarding.setup import setup_auto
from swag_bot.onboarding.status import doctor_report

app = typer.Typer(help="Set up Swag Bot and connect it to an MCP client.")


def _ask(question: str) -> bool:
    """Ask on the terminal, or on ``/dev/tty`` when stdin is a pipe."""
    prompt = question + " [y/N] "
    try:
        if sys.stdin.isatty():
            answer = input(prompt)
        else:
            with open("/dev/tty", encoding="utf-8") as tty:
                sys.stderr.write(prompt)
                sys.stderr.flush()
                answer = tty.readline()
    except (EOFError, OSError):
        return False
    return answer.strip().lower() in {"y", "yes"}


def _progress(line: str) -> None:
    print(line, file=sys.stderr)


def _choose(prompt: str) -> str:
    """Read a menu choice. Never echoes a secret. Returns '' when there is no tty."""
    try:
        if sys.stdin.isatty():
            return input(prompt)
        with open("/dev/tty", encoding="utf-8") as tty:
            sys.stderr.write(prompt)
            sys.stderr.flush()
            return tty.readline()
    except (EOFError, OSError):
        return ""


def _read_secret(prompt: str) -> str:
    """Read a key without echoing it. Returns '' when input is unavailable."""
    try:
        return getpass.getpass(prompt)
    except (EOFError, OSError):
        return ""


@app.command("setup")
def setup_command(
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help="Detect a key, Ollama, or a local server and write config.toml.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Pull the recommended model without asking again."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the decision. Do not write config or pull."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the doctor JSON after setup."),
    ] = False,
    grant: Annotated[
        list[str] | None,
        typer.Option("--grant", help="Preapprove a risk or action kind for MCP sessions."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            help="OpenAI-compatible server to use, for example http://localhost:1234/v1.",
        ),
    ] = None,
) -> None:
    """Detect a model, or record an MCP preapproval.

    With no flags this is ``--auto``. A model download is asked for first
    unless you pass ``--yes``.
    """
    try:
        if grant and dry_run:
            typer.echo("Dry run. Would preapprove: " + ", ".join(grant))
        else:
            for item in grant or []:
                stored = add_grant(item)
                typer.echo(
                    "Preapproved MCP grants: risks "
                    + (", ".join(stored.risks) or "(none)")
                    + "; kinds "
                    + (", ".join(stored.kinds) or "(none)")
                )
        if grant and not auto and not dry_run and not json_output:
            return
        result = setup_auto(
            assume_yes=yes,
            dry_run=dry_run,
            interactive=not yes and not dry_run and sys.stdin.isatty(),
            ask=_ask,
            progress=_progress,
            base_url=base_url,
            choose=_choose,
            read_secret=_read_secret,
            echo=typer.echo,
        )
    except (ConfigError, SwagError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(doctor_report(), indent=2, sort_keys=True))
    elif result.message:
        typer.echo(result.message)
    if result.exit_code:
        raise typer.Exit(code=result.exit_code)


@app.command("install-mcp")
def install_mcp_command(
    client: Annotated[
        str,
        typer.Option("--client", help="claude, cursor, vscode, gemini, desktop, chatgpt, or all."),
    ] = "all",
) -> None:
    """Print the install command or link for an MCP client."""
    names = ["claude", "cursor", "vscode", "gemini", "desktop", "chatgpt"]
    chosen = names if client.strip().lower() == "all" else [client]
    blocks: list[str] = []
    try:
        for name in chosen:
            blocks.append(render_client(name))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("\n\n".join(blocks))
