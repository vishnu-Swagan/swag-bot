"""``swag run`` command. Registered on the root app without a group name.

This module is the composition root. It calls the public factories in
models, memory, safety, mcp, and plugins. The loop itself does not import
those packages.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from swag_bot.config import Settings, load_settings
from swag_bot.core.artifacts import default_output_dir, write_run_artifacts
from swag_bot.core.display import TaskListView, display_status
from swag_bot.core.fallbacks import FallbackMemory, FallbackPolicy, FallbackPrompter
from swag_bot.core.fallbacks import LocalSandbox as FallbackSandbox
from swag_bot.core.loop import LoopEvent, PlanDoVerifyLoop
from swag_bot.core.tools import register_builtin_tools
from swag_bot.errors import NotImplementedYet, SwagError
from swag_bot.interfaces import (
    ApprovalPrompter,
    AutonomyLevel,
    MCPServerSpec,
    MemoryStore,
    PermissionPolicy,
    PluginRegistry,
    Sandbox,
    SkillMeta,
    StepStatus,
)
from swag_bot.mcp import build_mcp_client
from swag_bot.mcp.client import SwagMCPClient
from swag_bot.mcp.config import load_mcp_servers
from swag_bot.memory import build_memory_store
from swag_bot.models import build_llm_client
from swag_bot.plugins import build_registry
from swag_bot.registry import InMemoryToolRegistry
from swag_bot.safety import build_permission_policy, build_prompter, build_sandbox

app = typer.Typer(help="Plan, do, and verify a multi-step task.")


@dataclass(frozen=True)
class GoalResult:
    """What ``execute_goal`` returns to the CLI and to ``swag serve-mcp``."""

    summary: str
    output_dir: Path
    exit_code: int
    engine_note: str


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
    from swag_bot.onboarding.setup import first_run_if_needed

    first_run_if_needed(announce=typer.echo)
    if not goal.strip():
        typer.echo("goal must not be empty", err=True)
        raise typer.Exit(code=1)
    if max_steps < 1 or max_attempts < 1 or concurrency < 1:
        typer.echo("max-steps, max-attempts, and concurrency must be at least 1", err=True)
        raise typer.Exit(code=1)

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

    typer.echo(f"Planning: {goal}")
    try:
        with view:
            result = execute_goal(
                goal,
                autonomy=autonomy,
                model=model,
                output_dir=output_dir,
                max_steps=max_steps,
                dry_run=dry_run,
                concurrency=concurrency,
                max_attempts=max_attempts,
                engine=engine,
                on_event=on_event,
                announce=typer.echo,
            )
    except (ValueError, SwagError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(result.summary.rstrip())
    typer.echo(f"Output: {result.output_dir}")
    if result.exit_code:
        raise typer.Exit(code=result.exit_code)


def execute_goal(
    goal: str,
    *,
    autonomy: AutonomyLevel | None = None,
    model: str | None = None,
    output_dir: Path | None = None,
    max_steps: int = 8,
    dry_run: bool = False,
    concurrency: int = 4,
    max_attempts: int = 2,
    engine: str = "python",
    on_event: Callable[[LoopEvent], None] | None = None,
    announce: Callable[[str], None] | None = None,
    settings: Settings | None = None,
    prompter: ApprovalPrompter | None = None,
) -> GoalResult:
    """Run one goal with the configured model, sandbox, policy, tools, and memory.

    Recalls memories and selects plugin skills before planning. Saves the
    summary to memory after the run. MCP tools come from ``~/.swag/mcp.json``
    and from enabled plugins, on top of the built-in file and shell tools.
    """
    if not goal.strip():
        raise SwagError("goal must not be empty")
    if max_steps < 1 or max_attempts < 1 or concurrency < 1:
        raise SwagError("max-steps, max-attempts, and concurrency must be at least 1")

    active = load_settings() if settings is None else settings
    if autonomy is not None:
        active = active.model_copy(update={"autonomy": autonomy})
    if model:
        active = active.model_copy(
            update={"model": active.model.model_copy(update={"model": model})}
        )

    llm = build_llm_client(active)
    destination = output_dir if output_dir is not None else default_output_dir()
    destination.mkdir(parents=True, exist_ok=True)
    sandbox = _sandbox(active, destination)
    memory = _memory(active)
    policy = _policy(active, destination)
    active_prompter = prompter if prompter is not None else _prompter(active)
    plugins = _plugins(active)

    tools = InMemoryToolRegistry()
    register_builtin_tools(tools, sandbox)
    mcp_client = _attach_mcp_tools(tools, active, policy, active_prompter, plugins)
    context = _planner_context(goal, memory, plugins)

    try:
        loop = PlanDoVerifyLoop(
            llm=llm,
            sandbox=sandbox,
            memory=memory,
            policy=policy,
            prompter=active_prompter,
            tools=tools,
            model=active.model.model,
            max_steps=max_steps,
            max_attempts=max_attempts,
            concurrency=concurrency,
            engine=engine,
        )
    except (ValueError, SwagError):
        if mcp_client is not None:
            mcp_client.close()
        raise
    if loop.engine_note and announce is not None:
        announce(loop.engine_note)
    loop.on_event = on_event

    plan = None
    try:
        plan = loop.run(goal, dry_run=dry_run, context=context)
        _save_summary(memory, goal, loop.summary_text)
        failed = any(step.status == StepStatus.FAILED for step in plan.steps)
        return GoalResult(
            summary=loop.summary_text,
            output_dir=destination,
            exit_code=1 if failed else 0,
            engine_note=loop.engine_note,
        )
    finally:
        if plan is not None:
            write_run_artifacts(destination, plan, loop.action_log, loop.summary_text)
        if mcp_client is not None:
            mcp_client.close()


def mcp_task_runner(goal: str) -> str:
    """Run a goal for ``swag serve-mcp`` and return the summary text.

    The prompter is the one bound for this MCP request. It never reads stdin
    or writes stdout, because those streams are the stdio protocol channel.
    """
    from swag_bot.onboarding.approvals import current_mcp_prompter

    try:
        return execute_goal(goal, prompter=current_mcp_prompter()).summary
    except SwagError as exc:
        return str(exc)


def mcp_skill_provider() -> list[SkillMeta]:
    """Skill metadata for ``swag serve-mcp``. Bodies are not read."""
    try:
        return list(build_registry(load_settings()).list_skills())
    except SwagError:
        return []


def _sandbox(settings: Settings, workdir: Path) -> Sandbox:
    try:
        return build_sandbox(settings, workdir)
    except NotImplementedYet:
        return FallbackSandbox(workdir)


def _memory(settings: Settings) -> MemoryStore:
    try:
        return build_memory_store(settings)
    except NotImplementedYet:
        return FallbackMemory()


def _policy(settings: Settings, workdir: Path) -> PermissionPolicy:
    try:
        return build_permission_policy(settings, workdir=workdir)
    except NotImplementedYet:
        return FallbackPolicy(settings.autonomy)


def _prompter(settings: Settings) -> ApprovalPrompter:
    try:
        return build_prompter(settings)
    except NotImplementedYet:
        return FallbackPrompter()


def _plugins(settings: Settings) -> PluginRegistry | None:
    try:
        return build_registry(settings)
    except SwagError as exc:
        print(f"warning: plugins were not loaded: {exc}", file=sys.stderr)
        return None


def _planner_context(goal: str, memory: MemoryStore, plugins: PluginRegistry | None) -> str:
    sections: list[str] = []
    recalled = _recall(memory, goal)
    if recalled:
        lines = ["Relevant memories:", *[f"- {item}" for item in recalled]]
        sections.append("\n".join(lines))
    skills = _skill_instructions(goal, plugins)
    if skills:
        sections.append(skills)
    return "\n\n".join(sections)


def _recall(memory: MemoryStore, goal: str) -> list[str]:
    try:
        return [item.content for item in memory.search(goal, limit=5)]
    except Exception:
        return []


def _skill_instructions(goal: str, plugins: PluginRegistry | None) -> str:
    if plugins is None:
        return ""
    try:
        chosen = plugins.select_skills(goal, limit=5)
    except Exception:
        return ""
    blocks: list[str] = []
    for meta in chosen:
        try:
            body = plugins.load_skill(meta.name).instructions().strip()
        except (KeyError, OSError, SwagError):
            continue
        if body:
            blocks.append(f"### {meta.name}\n{body}")
    if not blocks:
        return ""
    return "Selected skills:\n\n" + "\n\n".join(blocks)


def _save_summary(memory: MemoryStore, goal: str, summary: str) -> None:
    text = summary.strip()
    if not text:
        return
    try:
        memory.add(text, metadata={"kind": "run-summary", "goal": goal})
    except Exception:
        return


def _attach_mcp_tools(
    registry: InMemoryToolRegistry,
    settings: Settings,
    policy: PermissionPolicy,
    prompter: ApprovalPrompter,
    plugins: PluginRegistry | None,
) -> SwagMCPClient | None:
    servers = _mcp_servers(settings, plugins)
    if not servers:
        return None
    client: SwagMCPClient | None = None
    try:
        client = build_mcp_client(settings, policy=policy, prompter=prompter, servers=servers)
        listed = client.list_tools()
    except Exception as exc:
        print(f"warning: MCP tools were not loaded: {exc}", file=sys.stderr)
        if client is not None:
            client.close()
        return None
    for tool in listed:
        registry.register(tool, _mcp_handler(client, tool.name))
    return client


def _mcp_servers(settings: Settings, plugins: PluginRegistry | None) -> list[MCPServerSpec]:
    """Plugin servers first. An entry in ``~/.swag/mcp.json`` with the same name wins."""
    merged: dict[str, MCPServerSpec] = {}
    if plugins is not None:
        try:
            for spec in plugins.list_mcp_servers():
                merged[spec.name] = spec
        except Exception as exc:
            print(f"warning: plugin MCP servers were not loaded: {exc}", file=sys.stderr)
    try:
        configured = load_mcp_servers()
    except SwagError as exc:
        print(f"warning: MCP config was not loaded: {exc}", file=sys.stderr)
        configured = {}
    for name, spec in configured.items():
        merged[name] = spec
    return list(merged.values())


def _mcp_handler(client: SwagMCPClient, name: str) -> Callable[..., str]:
    def handler(**arguments: Any) -> str:
        # The executor already applied the permission policy. Still honor a hard deny.
        return client.call_tool(name, arguments, authorized=True)

    return handler
