"""``swag run`` command. Registered on the root app without a group name."""

from typing import Annotated

import typer

from swag_bot.errors import unimplemented

app = typer.Typer(help="Plan, do, and verify a multi-step task.")


@app.command("run")
def run(
    goal: Annotated[str, typer.Argument(help="What Swag Bot should accomplish.")],
) -> None:
    """Plan, do, and verify a multi-step task."""
    unimplemented("swag run")
