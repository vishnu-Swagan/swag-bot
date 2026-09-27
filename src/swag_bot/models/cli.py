"""``swag model`` commands."""

import typer

from swag_bot.errors import unimplemented

app = typer.Typer(
    help="LLM providers (LiteLLM, Ollama, bring-your-own-key).",
    no_args_is_help=True,
)


@app.command("list")
def list_providers() -> None:
    """List model providers configured for this install."""
    unimplemented("swag model list")
