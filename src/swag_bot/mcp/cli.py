"""``swag mcp`` and the body of ``swag serve-mcp``."""

import typer

from swag_bot.errors import unimplemented

app = typer.Typer(help="MCP client and server.", no_args_is_help=True)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Expose Swag Bot as an MCP server.

    The root ``swag serve-mcp`` command calls this function. Implement the
    server here and keep the parameter names, so the root wrapper can pass
    ``host`` and ``port`` through.
    """
    unimplemented("swag serve-mcp")


def list_tools() -> None:
    """List tools from configured MCP servers."""
    unimplemented("swag mcp tools")


app.command("serve")(serve)
app.command("tools")(list_tools)
