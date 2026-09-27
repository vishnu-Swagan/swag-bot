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
from swag_bot.core.cli import mcp_skill_provider, mcp_task_runner
from swag_bot.errors import ConfigError, SwagError
from swag_bot.mcp.cli import app as mcp_app
from swag_bot.mcp.cli import configure_server
from swag_bot.mcp.cli import serve as mcp_serve
from swag_bot.memory.cli import app as memory_app
from swag_bot.memory.status import describe_memory
from swag_bot.models.cli import app as models_app
from swag_bot.models.hints import configured_model_line
from swag_bot.onboarding.cli import app as onboarding_app
from swag_bot.plugins.cli import app as plugins_app
from swag_bot.plugins.cli import skill_app
from swag_bot.plugins.installer import configure_grant_store
from swag_bot.safety.cli import app as safety_app
from swag_bot.safety.cli import undo_command
from swag_bot.safety.grants import JsonGrantStore

configure_server(runner=mcp_task_runner, skills_provider=mcp_skill_provider)
configure_grant_store(JsonGrantStore())

app = typer.Typer(
    name="swag",
    help="Swag Bot: free, open-source agent for multi-step tasks.",
    no_args_is_help=True,
)

app.add_typer(core_app)
app.add_typer(plugins_app, name="plugin")
app.add_typer(skill_app, name="skill")
app.add_typer(safety_app, name="safety")
app.add_typer(mcp_app, name="mcp")
app.add_typer(models_app, name="model")
app.add_typer(memory_app, name="memory")
app.add_typer(onboarding_app)
app.command("undo")(undo_command)

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
    host: Annotated[str, typer.Option(help="Bind address when using HTTP.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port when using HTTP.")] = 8765,
    http: Annotated[
        bool,
        typer.Option("--http", help="Serve streamable HTTP instead of stdio."),
    ] = False,
) -> None:
    """Expose Swag Bot as an MCP server. Stdio is the default."""
    mcp_serve(host=host, port=port, http=http)


@app.command()
def version() -> None:
    """Print the Swag Bot version."""
    typer.echo(f"swag-bot {__version__}")


@app.command()
def doctor(
    probe: Annotated[
        bool,
        typer.Option(
            "--probe",
            help="Probe the configured model and print its cached capability profile.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print a JSON readiness report. No secret values."),
    ] = False,
) -> None:
    """Print the active config and which optional dependencies are installed."""
    if json_output:
        import json

        from swag_bot.onboarding.status import doctor_report

        try:
            payload = doctor_report()
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
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
    model_check = configured_model_line(settings)
    if model_check:
        table.add_row("model.check", model_check)
    table.add_row("model.harness", settings.model.harness)
    if settings.model.timeout is None:
        timeout = "client default (120s)"
    else:
        timeout = f"{settings.model.timeout:g}s"
    table.add_row("model.timeout", timeout)
    fallback = settings.model.fallback
    if fallback.provider and fallback.model:
        fallback_label = f"{fallback.provider}/{fallback.model}"
    else:
        fallback_label = "(none)"
    table.add_row("model.fallback", fallback_label)
    budget = settings.model.budget
    table.add_row(
        "model.budget",
        f"{budget.max_escalations} escalations, {budget.max_extra_seconds:g}s, "
        f"${budget.max_cost_usd:g}",
    )
    table.add_row("autonomy", settings.autonomy.value)
    dirs = ", ".join(settings.plugin_dirs) if settings.plugin_dirs else "(none)"
    table.add_row("plugin_dirs", dirs)
    memory = describe_memory(settings)
    table.add_row("memory.backend", memory.backend_label)
    table.add_row("memory.path", memory.path_label)
    table.add_row("memory.mode", memory.mode)
    table.add_row("sandbox.mode", settings.sandbox.mode.value)
    table.add_row("sandbox.image", settings.sandbox.image)
    table.add_row("sandbox.network", str(settings.sandbox.network).lower())
    table.add_row("undo.enabled", str(settings.undo.enabled).lower())
    table.add_row("undo.auto_rollback", str(settings.undo.auto_rollback).lower())
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
    if probe:
        from swag_bot.harness.probe import profile_model, render_report
        from swag_bot.models import get_llm_client

        try:
            client = get_llm_client(settings)
            report = profile_model(
                client=client,
                provider=settings.model.provider,
                model=settings.model.model,
                api_base=settings.model.api_base,
            )
        except (ConfigError, SwagError) as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
        console.print(render_report(report))


def main() -> None:
    """Console-script entry point."""
    from swag_bot.onboarding.secrets import apply_saved_keys

    apply_saved_keys()
    app()
