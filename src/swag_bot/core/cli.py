"""``swag run`` command. Registered on the root app without a group name."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, TypeVar

import typer

from swag_bot.config import Settings, load_settings
from swag_bot.core.artifacts import default_output_dir, write_run_artifacts
from swag_bot.core.display import TaskListView, display_status
from swag_bot.core.fallbacks import FallbackMemory, FallbackPolicy, FallbackPrompter, LocalSandbox
from swag_bot.core.loop import LoopEvent, PlanDoVerifyLoop
from swag_bot.errors import NotImplementedYet, SwagError
from swag_bot.interfaces import AutonomyLevel, StepStatus
from swag_bot.memory import build_memory_store
from swag_bot.models import build_llm_client
from swag_bot.safety import build_permission_policy, build_prompter, build_sandbox

app = typer.Typer(help="Plan, do, and verify a multi-step task.")


@app.command("run")
def run(
    goal: Annotated[str, typer.Argument(help="What Swag Bot should accomplish.")],
    autonomy: Annotated[
        AutonomyLevel | None,
        typer.Option(help="Override the configured autonomy level."),
    ] = None,
    model: Annotated[str | None, typer.Option(help="Override the configured model name.")] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            help="Directory for plan.json, action-log.jsonl, and summary.md. "
            "Defaults to ./swag-output/<UTC timestamp>."
        ),
    ] = None,
    max_steps: Annotated[int, typer.Option(help="Maximum number of plan steps.")] = 8,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Plan only. Do not run steps."),
    ] = False,
    concurrency: Annotated[
        int,
        typer.Option(help="How many independent steps may run at once."),
    ] = 4,
    max_attempts: Annotated[
        int,
        typer.Option(help="How many times a step may be tried before it fails."),
    ] = 2,
    engine: Annotated[
        str,
        typer.Option(help="Workflow engine: python (default), graphbit, or auto."),
    ] = "python",
) -> None:
    """Plan, do, and verify a multi-step task."""
    if not goal.strip():
        typer.echo("goal must not be empty", err=True)
        raise typer.Exit(code=1)
    if max_steps < 1 or max_attempts < 1 or concurrency < 1:
        typer.echo("max-steps, max-attempts, and concurrency must be at least 1", err=True)
        raise typer.Exit(code=1)

    settings = load_settings()
    if autonomy is not None:
        settings = settings.model_copy(update={"autonomy": autonomy})
    if model:
        settings = settings.model_copy(
            update={"model": settings.model.model_copy(update={"model": model})}
        )

    try:
        llm = build_llm_client(settings)
    except NotImplementedYet as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    destination = output_dir if output_dir is not None else default_output_dir()
    destination.mkdir(parents=True, exist_ok=True)
    sandbox = _or_fallback(build_sandbox, settings, lambda: LocalSandbox(destination))
    memory = _or_fallback(build_memory_store, settings, FallbackMemory)
    policy = _or_fallback(
        build_permission_policy,
        settings,
        lambda: FallbackPolicy(settings.autonomy),
    )
    prompter = _or_fallback(build_prompter, settings, FallbackPrompter)

    try:
        loop = PlanDoVerifyLoop(
            llm=llm,
            sandbox=sandbox,
            memory=memory,
            policy=policy,
            prompter=prompter,
            model=settings.model.model,
            max_steps=max_steps,
            max_attempts=max_attempts,
            concurrency=concurrency,
            engine=engine,
        )
    except (ValueError, SwagError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if loop.engine_note:
        typer.echo(loop.engine_note)

    shown: dict[str, str] = {}
    view = TaskListView()

    def on_event(event: LoopEvent) -> None:
        if event.kind in {"plan", "status"}:
            view.update(event.plan)
            for step in event.plan.steps:
                if event.kind == "status" and event.step_id not in {None, step.id}:
                    continue
                label = display_status(step.status)
                if shown.get(step.id) == label:
                    continue
                shown[step.id] = label
                typer.echo(f"[{label}] {step.id} {step.title}")
        elif event.text:
            prefix = f"[{event.step_id}] " if event.step_id else ""
            view.stream(f"{prefix}{event.text}")
            typer.echo(f"{prefix}{event.text}")

    loop.on_event = on_event
    typer.echo(f"Planning: {goal}")
    plan = None
    try:
        with view:
            plan = loop.run(goal, dry_run=dry_run)
    except SwagError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if plan is not None:
            write_run_artifacts(destination, plan, loop.action_log, loop.summary_text)

    typer.echo(loop.summary_text.rstrip())
    typer.echo(f"Output: {destination}")
    if any(step.status == StepStatus.FAILED for step in plan.steps):
        raise typer.Exit(code=1)


_T = TypeVar("_T")


def _or_fallback(
    factory: Callable[[Settings], _T],
    settings: Settings,
    fallback: Callable[[], _T],
) -> _T:
    try:
        return factory(settings)
    except NotImplementedYet:
        return fallback()
