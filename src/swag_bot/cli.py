"""Root Typer app.

Registers each owned package's sub-app, plus ``swag version`` and
``swag doctor``. Owning agents add commands on their own ``cli.py``.
The safety/mcp agent may change the ``serve-mcp`` wrapper below so it stays
in sync with ``swag_bot.mcp.cli.serve``. Do not remove another area's command.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from swag_bot import __version__
from swag_bot.config import config_path, load_settings
from swag_bot.core.cli import app as core_app
from swag_bot.errors import ConfigError
from swag_bot.mcp.cli import app as mcp_app
from swag_bot.mcp.cli import serve as mcp_serve
from swag_bot.memory.cli import app as memory_app
from swag_bot.models.cli import app as models_app
from swag_bot.plugins.cli import app as plugins_app
from swag_bot.safety.cli import app as safety_app

app = typer.Typer(
    name="swag",
    help="Swag Bot: free, open-source agent for multi-step tasks.",
    no_args_is_help=True,
)

app.add_typer(core_app)
app.add_typer(plugins_app, name="plugin")
app.add_typer(safety_app, name="safety")
app.add_typer(mcp_app, name="mcp")
app.add_typer(models_app, name="model")
app.add_typer(memory_app, name="memory")

# Names only. doctor prints "set" or "unset" and never the value.
_SECRET_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
)

_OPTIONAL_MODULES = (
    ("litellm", "LiteLLM multi-provider client"),
    ("mcp", "MCP Python SDK"),
    ("docker", "Docker SDK for the sandbox"),
)

_OPTIONAL_BINARIES = ("docker", "ollama")


@app.command("serve-mcp")
def serve_mcp(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8765,
) -> None:
    """Expose Swag Bot as an MCP server."""
    mcp_serve(host=host, port=port)


@app.command()
def version() -> None:
    """Print the Swag Bot version."""
    typer.echo(f"swag-bot {__version__}")


@app.command()
def doctor() -> None:
    """Print the active config and which optional dependencies are installed."""
    console = Console(no_color=True, soft_wrap=True)
    path = config_path()
    try:
        settings = load_settings()
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    table = Table(title="swag doctor", show_header=True, header_style="bold")
    table.add_column("item")
    table.add_column("value")
    table.add_row("version", __version__)
    config_state = str(path) if path.is_file() else f"absent, defaults in use ({path})"
    table.add_row("config file", config_state)
    table.add_row("model.provider", settings.model.provider)
    table.add_row("model.model", settings.model.model)
    table.add_row("model.api_base", settings.model.api_base or "(provider default)")
    table.add_row("autonomy", settings.autonomy.value)
    dirs = ", ".join(settings.plugin_dirs) if settings.plugin_dirs else "(none)"
    table.add_row("plugin_dirs", dirs)
    table.add_row("memory.backend", settings.memory.backend)
    table.add_row("memory.path", settings.memory.path or "(none)")
    table.add_row("sandbox.mode", settings.sandbox.mode.value)
    table.add_row("sandbox.image", settings.sandbox.image)
    table.add_row("sandbox.network", str(settings.sandbox.network).lower())
    for name in _SECRET_ENV_VARS:
        state = "set" if os.environ.get(name) else "unset"
        table.add_row(name, state)
    for module_name, label in _OPTIONAL_MODULES:
        found = importlib.util.find_spec(module_name) is not None
        state = "installed" if found else "not installed"
        table.add_row(f"module {module_name}", f"{state} ({label})")
    for binary in _OPTIONAL_BINARIES:
        located = shutil.which(binary)
        table.add_row(f"binary {binary}", located or "not found")
    console.print(table)
    console.print("API keys are read from the environment and are not displayed.")


def main() -> None:
    """Console-script entry point."""
    app()
