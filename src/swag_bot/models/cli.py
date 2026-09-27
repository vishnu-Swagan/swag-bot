"""``swag model`` commands."""

from __future__ import annotations

import os
from typing import Annotated

import typer

from swag_bot.config import Settings, load_settings, save_settings
from swag_bot.errors import ConfigError, SwagError
from swag_bot.models.factory import KNOWN_PROVIDERS, get_llm_client, split_provider_model
from swag_bot.models.hints import availability_line, model_matches
from swag_bot.models.keys import key_status, redact_secrets
from swag_bot.models.ollama import OllamaClient, resolve_ollama_base_url

app = typer.Typer(
    help="LLM providers (LiteLLM, Ollama, bring-your-own-key).",
    no_args_is_help=True,
)


@app.command("list")
def list_providers() -> None:
    """Show providers, whether keys are set, and local Ollama models."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        _fail(str(exc))
        return
    typer.echo(render_provider_report(settings))


@app.command("test")
def test_model(
    prompt: Annotated[
        str,
        typer.Argument(help="Short prompt. Defaults to a one-word check."),
    ] = "Reply with the single word: ok",
) -> None:
    """Send one short prompt to the configured model."""
    try:
        settings = load_settings()
        if settings.model.provider.strip().lower() == "ollama":
            names = OllamaClient(
                model=settings.model.model,
                base_url=resolve_ollama_base_url(settings.model.api_base),
            ).list_models(timeout=1.0)
            if names is not None and not model_matches(settings.model.model, names):
                _fail(availability_line(settings.model.model, names))
                return
        client = get_llm_client(settings)
        text = client.complete(prompt)
    except (ConfigError, SwagError) as exc:
        _fail(redact_secrets(str(exc)))
        return
    typer.echo(text)


@app.command("probe")
def probe_model(
    force: Annotated[
        bool,
        typer.Option("--force", help="Ignore the cached profile and probe again."),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the profile as JSON."),
    ] = False,
) -> None:
    """Probe the configured model once and cache JSON, tool, and context scores."""
    from swag_bot.harness.probe import profile_model, render_report

    try:
        settings = load_settings()
        client = get_llm_client(settings)
        report = profile_model(
            client=client,
            provider=settings.model.provider,
            model=settings.model.model,
            api_base=settings.model.api_base,
            force=force,
        )
    except (ConfigError, SwagError) as exc:
        _fail(redact_secrets(str(exc)))
        return
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(render_report(report))


@app.command("set")
def set_model(
    spec: Annotated[str, typer.Argument(help="provider/model, for example ollama/llama3.2.")],
) -> None:
    """Save ``provider`` and ``model`` in the config file. Does not store keys."""
    try:
        provider, model = split_provider_model(spec)
        settings = load_settings()
    except ConfigError as exc:
        _fail(str(exc))
        return
    settings.model.provider = provider
    settings.model.model = model
    path = save_settings(settings)
    typer.echo(f"model set to {provider}/{model}")
    typer.echo(f"wrote {path}")


def render_provider_report(settings: Settings | None = None) -> str:
    """Text report for ``swag model list``. Key values are never included."""
    loaded = load_settings() if settings is None else settings
    active = f"{loaded.model.provider}/{loaded.model.model}"
    lines = [f"active: {active}", "providers:"]
    # Probe the active api_base when Ollama is selected. Otherwise probe
    # OLLAMA_HOST so a local daemon still shows up next to cloud providers.
    if loaded.model.provider == "ollama":
        ollama_base = resolve_ollama_base_url(loaded.model.api_base)
    else:
        ollama_base = resolve_ollama_base_url(os.environ.get("OLLAMA_HOST"))
    names = OllamaClient(model=loaded.model.model, base_url=ollama_base).list_models(timeout=1.0)
    if names is None:
        local = "unreachable"
    elif names:
        local = ", ".join(names)
    else:
        local = "(none)"
    lines.append(f"  ollama      local  no key  endpoint {ollama_base}  models: {local}")
    if loaded.model.provider.strip().lower() == "ollama":
        lines.append(availability_line(loaded.model.model, names))
    for provider, env_var, present in key_status():
        state = "set" if present else "unset"
        lines.append(f"  {provider:<11} cloud  {env_var}={state}")
    lines.append(
        "  litellm     cloud  uses the key for the model prefix (optional extra .[models])"
    )
    lines.append("API keys are read from the environment and are not displayed.")
    lines.append("known: " + ", ".join(sorted(KNOWN_PROVIDERS)))
    return "\n".join(lines)


def _fail(message: str) -> None:
    typer.echo(redact_secrets(message), err=True)
    raise typer.Exit(code=1)
