"""``swag replay`` and ``swag bundle`` commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from swag_bot.config import load_settings
from swag_bot.core.bundle.replay import replay_run
from swag_bot.core.bundle.store import describe_bundle, export_bundle, load_bundle
from swag_bot.errors import SwagError
from swag_bot.models import build_llm_client

bundle_app = typer.Typer(help="Inspect and export a recorded run bundle.")


def replay_command(
    bundle: Annotated[Path, typer.Argument(help="Bundle directory or .zip file.")],
    mode: Annotated[
        str,
        typer.Option(help="recorded uses saved model responses. live calls a model and compares."),
    ] = "recorded",
    model: Annotated[
        str | None,
        typer.Option(help="Model name for --mode live. Recorded mode ignores this."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(help="Where the replay writes files. Defaults to ./swag-replay/<timestamp>."),
    ] = None,
    tools: Annotated[
        str,
        typer.Option(help="rerun executes tools again. recorded returns the saved tool results."),
    ] = "rerun",
) -> None:
    """Re-execute a bundle offline, or live against another model."""
    client = None
    if mode == "live":
        settings = load_settings()
        if model:
            settings = settings.model_copy(
                update={"model": settings.model.model_copy(update={"model": model})}
            )
        try:
            client = build_llm_client(settings)
        except SwagError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    try:
        report = replay_run(
            bundle,
            mode=mode,
            llm=client,
            workdir=output_dir,
            tool_mode=tools,
        )
    except (ValueError, SwagError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Replay mode: {report.mode}")
    typer.echo(f"Goal: {report.goal}")
    for step_id, status in report.step_status.items():
        typer.echo(f"[{status}] {step_id}")
    if report.differences:
        typer.echo("Differences:")
        for item in report.differences:
            typer.echo(f"- {item}")
    else:
        typer.echo("Matched the bundle.")
    typer.echo(f"Output: {report.output_dir}")
    if not report.matched:
        raise typer.Exit(code=1)


@bundle_app.command("inspect")
def inspect_bundle(
    bundle: Annotated[Path, typer.Argument(help="Bundle directory or .zip file.")],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the manifest as JSON."),
    ] = False,
) -> None:
    """Print what a bundle contains, without running it."""
    try:
        loaded = load_bundle(bundle)
    except SwagError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    try:
        if as_json:
            typer.echo(json.dumps(loaded.manifest, indent=2, sort_keys=True))
        else:
            typer.echo(describe_bundle(loaded))
    finally:
        loaded.close()


@bundle_app.command("export")
def export_bundle_cmd(
    bundle: Annotated[Path, typer.Argument(help="Bundle directory or .zip file.")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Zip file to write."),
    ],
) -> None:
    """Zip a bundle so it can be attached to a bug report."""
    try:
        written = export_bundle(bundle, output)
    except SwagError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Exported: {written}")
