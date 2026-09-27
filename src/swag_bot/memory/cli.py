"""``swag memory`` commands."""

from typing import Annotated

import typer

from swag_bot.errors import unimplemented

app = typer.Typer(help="Pluggable memory store.", no_args_is_help=True)


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Text to search for.")],
) -> None:
    """Search the memory store."""
    unimplemented("swag memory search")
