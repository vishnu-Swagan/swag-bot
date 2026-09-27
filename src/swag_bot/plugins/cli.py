"""``swag plugin`` commands."""

from pathlib import Path
from typing import Annotated

import typer

from swag_bot.errors import unimplemented

app = typer.Typer(
    help="Install and inspect Cowork-compatible plugins.",
    no_args_is_help=True,
)


@app.command("list")
def list_plugins() -> None:
    """List discovered plugins."""
    unimplemented("swag plugin list")


@app.command("show")
def show(
    name: Annotated[str, typer.Argument(help="Plugin name.")],
) -> None:
    """Show one plugin's manifest."""
    unimplemented("swag plugin show")


@app.command("validate")
def validate(
    path: Annotated[
        Path,
        typer.Argument(help="Plugin root (the directory that contains .claude-plugin/)."),
    ],
) -> None:
    """Validate a Cowork / Claude Code plugin directory."""
    unimplemented("swag plugin validate")
