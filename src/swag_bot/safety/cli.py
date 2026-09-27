"""``swag safety`` commands."""

import typer

from swag_bot.errors import unimplemented

app = typer.Typer(
    help="Permissions, autonomy, and the action log.",
    no_args_is_help=True,
)


@app.command("log")
def show_log() -> None:
    """Print the action log."""
    unimplemented("swag safety log")


@app.command("policy")
def show_policy() -> None:
    """Print the autonomy level and risk rules."""
    unimplemented("swag safety policy")
