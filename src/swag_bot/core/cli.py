"""``swag run`` command. Registered on the root app without a group name.

This module is the composition root. It calls the public factories in
models, memory, safety, mcp, and plugins. The loop itself does not import
those packages.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from swag_bot.config import EscalationSettings, Settings, TaintMode, load_settings
from swag_bot.core.artifacts import default_output_dir, write_run_artifacts
from swag_bot.core.display import PromptSuspender, RunProgress, TaskListView
from swag_bot.core.escalation import EscalationController, build_escalation
from swag_bot.core.fallbacks import FallbackMemory, FallbackPolicy, FallbackPrompter
from swag_bot.core.fallbacks import LocalSandbox as FallbackSandbox
from swag_bot.core.loop import LoopEvent, PlanDoVerifyLoop
from swag_bot.core.memory_journal import (
    append_remembered,
    commit_memory,
    normalize_memory_mode,
    provenance_metadata,
    recall_lines,
)
from swag_bot.core.reversibility import (
    ReversibilityClassifier,
    StubReversibilityClassifier,
    adapt_classifier,
)
from swag_bot.core.tools import register_builtin_tools
from swag_bot.errors import ConfigError, NotImplementedYet, SwagError
from swag_bot.interfaces import (
    ActionLogEntry,
    ApprovalPrompter,
    AutonomyLevel,
    LLMClient,
    MCPServerSpec,
    MemoryItem,
    MemoryStore,
    PermissionPolicy,
    PluginRegistry,
    Sandbox,
    SkillMeta,
    StepStatus,
    TaintTracker,
    TrustLevel,
)
from swag_bot.mcp import build_mcp_client
from swag_bot.mcp.client import SwagMCPClient
from swag_bot.mcp.config import load_mcp_servers
from swag_bot.mcp.registry import compensation_annotation
from swag_bot.memory import build_memory_store
from swag_bot.models import build_llm_client
from swag_bot.models.factory import split_provider_model
from swag_bot.plugins import build_registry
from swag_bot.registry import InMemoryToolRegistry
from swag_bot.safety import (
    build_permission_policy,
    build_prompter,
    build_sandbox,
    build_taint_tracker,
)
from swag_bot.safety.compensation import CompensationRegistry
from swag_bot.safety.log import ActionLog
from swag_bot.safety.undo import UndoLedger, UndoSandbox

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
            help="Directory for plan.json, action-log.jsonl, run.jsonl, and summary.md. "
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
    strict_plan: Annotated[
        bool,
        typer.Option(
            "--strict-plan",
            help="Stop if the model plan cannot be parsed. Do not fall back to one step.",
        ),
    ] = False,
    memory_mode: Annotated[
        str | None,
        typer.Option(
            "--memory-mode",
            help="ask, auto, or off. Overrides memory.mode for this run.",
        ),
    ] = None,
    evidence: Annotated[
        bool | None,
        typer.Option(
            "--evidence/--no-evidence",
            help="Require cited evidence for a passing step. Default follows config.",
        ),
    ] = None,
    taint_mode: Annotated[
        str | None,
        typer.Option(
            "--taint-mode",
            help="Taint firewall: escalate (ask, show the source), block, or off.",
        ),
    ] = None,
    escalate: Annotated[
        bool | None,
        typer.Option(
            "--escalate/--no-escalate",
            help=(
                "Ask a clarifying question when a step is uncertain, and require a "
                "jury before an irreversible action. Overrides escalation.enabled."
            ),
        ),
    ] = None,
) -> None:
    """Plan, do, and verify a multi-step task."""
    if not goal.strip():
        typer.echo("goal must not be empty", err=True)
        raise typer.Exit(code=1)
    if max_steps < 1 or max_attempts < 1 or concurrency < 1:
        typer.echo("max-steps, max-attempts, and concurrency must be at least 1", err=True)
        raise typer.Exit(code=1)

    view = TaskListView()
    progress = RunProgress(view)

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
                on_event=progress,
                announce=view.note,
                strict_plan=strict_plan,
                memory_mode=memory_mode,
                display=view,
                evidence=evidence,
                taint_mode=taint_mode,
                escalate=escalate,
            )
    except (ValueError, SwagError) as exc:
        view.print_final()
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    view.print_final()

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
    strict_plan: bool = False,
    memory_mode: str | None = None,
    display: TaskListView | None = None,
    evidence: bool | None = None,
    taint_mode: str | None = None,
    escalate: bool | None = None,
) -> GoalResult:
    """Run one goal with the configured model, sandbox, policy, tools, and memory.

    Recalls memories and selects plugin skills before planning. Saves the
    summary to memory after the run. MCP tools come from ``$SWAG_HOME/mcp.json``
    and from enabled plugins, on top of the built-in file and shell tools.
    """
    if not goal.strip():
        raise SwagError("goal must not be empty")
    if max_steps < 1 or max_attempts < 1 or concurrency < 1:
        raise SwagError("max-steps, max-attempts, and concurrency must be at least 1")
    chosen_memory: str | None = None
    if memory_mode is not None:
        try:
            chosen_memory = normalize_memory_mode(memory_mode)
        except ValueError as exc:
            raise SwagError(str(exc)) from exc

    active = load_settings() if settings is None else settings
    if autonomy is not None:
        active = active.model_copy(update={"autonomy": autonomy})
    if model:
        active = active.model_copy(
            update={"model": active.model.model_copy(update={"model": model})}
        )
    if chosen_memory is not None:
        active = active.model_copy(
            update={"memory": active.memory.model_copy(update={"mode": chosen_memory})}
        )
    if taint_mode is not None:
        try:
            chosen_taint = TaintMode(taint_mode)
        except ValueError as exc:
            raise SwagError("taint mode must be escalate, block, or off") from exc
        active = active.model_copy(
            update={"taint": active.taint.model_copy(update={"mode": chosen_taint})}
        )

    llm = build_llm_client(active)
    destination = output_dir if output_dir is not None else default_output_dir()
    destination.mkdir(parents=True, exist_ok=True)
    sandbox = _sandbox(active, destination)
    memory = _memory(active)
    policy = _policy(active, destination)
    prompter = _prompter(active)
    if display is not None:
        prompter = PromptSuspender(prompter, display)
    plugins = _plugins(active)
    if active.memory.mode == "off" and announce is not None:
        announce("memory off: this run will not read or write memory")
    sandbox, undo = _attach_undo(active, destination, sandbox, policy, plugins)

    tracker = build_taint_tracker(active, llm=llm)
    if tracker is not None:
        tracker.note(goal, source="user", trust=TrustLevel.TRUSTED)
    tools = InMemoryToolRegistry()
    register_builtin_tools(tools, sandbox)
    mcp_client = _attach_mcp_tools(tools, active, policy, prompter, plugins, tracker)
    if undo is not None:
        _note_mcp_compensations(undo, tools)
    context = _planner_context(
        goal,
        memory,
        plugins,
        tracker,
        active.taint.memory,
        announce=announce,
        mode=active.memory.mode,
    )
    escalation = _escalation(active, llm, destination, escalate=escalate, announce=announce)

    try:
        evidence_enabled = active.evidence.enabled if evidence is None else evidence
        home_log = ActionLog()

        def persist(entry: ActionLogEntry) -> None:
            home_log.append(entry)

        loop = PlanDoVerifyLoop(
            llm=llm,
            sandbox=sandbox,
            memory=memory,
            policy=policy,
            prompter=prompter,
            tools=tools,
            model=active.model.model,
            max_steps=max_steps,
            max_attempts=max_attempts,
            concurrency=concurrency,
            engine=engine,
            strict_plan=strict_plan,
            memory_mode=active.memory.mode,
            action_sink=persist,
            evidence_dir=destination,
            evidence_enabled=evidence_enabled,
            undo=undo,
            taint=tracker,
            escalation=escalation,
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
        saved = _save_summary(
            memory,
            goal,
            loop.summary_text,
            mode=active.memory.mode,
            prompter=prompter,
            run_id=plan.id,
            announce=announce,
        )
        if saved:
            loop.summary_text = append_remembered(loop.summary_text, saved)
        failed = any(
            step.status in {StepStatus.FAILED, StepStatus.UNVERIFIED} for step in plan.steps
        )
        return GoalResult(
            summary=loop.summary_text,
            output_dir=destination,
            exit_code=1 if failed else 0,
            engine_note=loop.engine_note,
        )
    finally:
        if plan is not None:
            write_run_artifacts(
                destination, plan, loop.action_log, loop.summary_text, ledger=loop.ledger
            )
        if mcp_client is not None:
            mcp_client.close()


def mcp_task_runner(goal: str) -> str:
    """Run a goal for ``swag serve-mcp`` and return the summary text.

    Stdout stays quiet so it does not corrupt a stdio MCP session.
    """
    try:
        return execute_goal(goal).summary
    except SwagError as exc:
        return str(exc)


def mcp_skill_provider() -> list[SkillMeta]:
    """Skill metadata for ``swag serve-mcp``. Bodies are not read."""
    try:
        return list(build_registry(load_settings()).list_skills())
    except SwagError:
        return []


def _attach_undo(
    settings: Settings,
    workdir: Path,
    sandbox: Sandbox,
    policy: PermissionPolicy,
    plugins: PluginRegistry | None,
) -> tuple[Sandbox, UndoLedger | None]:
    """Wrap ``sandbox`` so writes and shell commands snapshot first.

    Disabled with ``undo.enabled = false``. The default autonomy stays
    ``ask-risky``; this only records restore points.
    """
    if not settings.undo.enabled:
        return sandbox, None
    registry = CompensationRegistry()
    if plugins is not None:
        try:
            for plugin in plugins.list_plugins():
                registry.load_entries(
                    list(plugin.manifest.compensations),
                    source=plugin.manifest.name,
                )
        except Exception as exc:
            print(f"warning: compensations were not loaded: {exc}", file=sys.stderr)
    bind = getattr(policy, "bind_compensations", None)
    if callable(bind):
        bind(registry)
    ledger = UndoLedger.open(
        workdir,
        compensations=registry,
        auto_rollback=settings.undo.auto_rollback,
    )
    return UndoSandbox(sandbox, ledger), ledger


def _note_mcp_compensations(ledger: UndoLedger, tools: InMemoryToolRegistry) -> None:
    for tool in tools.list_tools():
        raw = compensation_annotation(tool)
        if raw is None:
            continue
        entry = dict(raw)
        if "tool" not in entry and "name" not in entry:
            entry["tool"] = tool.name
        ledger.compensations.load_entries([entry], source=tool.name)


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


def _escalation(
    settings: Settings,
    llm: LLMClient,
    workdir: Path,
    *,
    escalate: bool | None,
    announce: Callable[[str], None] | None,
) -> EscalationController | None:
    """Build the uncertainty gate when this run asked for it.

    ``escalate`` True or False overrides ``escalation.enabled``. None keeps
    the config value, which defaults to off.
    """
    chosen = _escalation_settings(settings.escalation, escalate)
    if not chosen.enabled:
        return None
    label = f"{settings.model.provider}/{settings.model.model}"
    return build_escalation(
        chosen,
        llm=llm,
        judges=_judges(settings, llm, announce),
        classifier=_reversibility_classifier(workdir),
        session_label=label,
    )


def _reversibility_classifier(workdir: Path) -> ReversibilityClassifier:
    """Use the undo ledger's classifier when it has landed, else the stub."""
    try:
        module = importlib.import_module("swag_bot.safety.reversibility")
    except ImportError:
        return StubReversibilityClassifier()
    return adapt_classifier(getattr(module, "classify_reversibility", None), workdir)


def _escalation_settings(settings: EscalationSettings, escalate: bool | None) -> EscalationSettings:
    if escalate is None:
        return settings
    return settings.model_copy(update={"enabled": escalate})


def _judges(
    settings: Settings,
    llm: LLMClient,
    announce: Callable[[str], None] | None,
) -> list[tuple[str, LLMClient]]:
    """Judge clients from ``escalation.judges``. Empty means the session model.

    A judge that cannot be built is skipped. If every judge fails, the session
    model is used so a single local model still runs the panel.
    """
    specs = settings.escalation.judges
    if not specs:
        return []
    built: list[tuple[str, LLMClient]] = []
    for spec in specs:
        try:
            provider, model = split_provider_model(spec)
        except ConfigError as exc:
            _warn(announce, f"skipping jury judge {spec!r}: {exc}")
            continue
        try:
            client = build_llm_client(
                settings.model_copy(
                    update={
                        "model": settings.model.model_copy(
                            update={"provider": provider, "model": model, "api_base": None}
                        )
                    }
                )
            )
        except Exception as exc:
            _warn(announce, f"skipping jury judge {spec!r}: {exc}")
            continue
        built.append((f"{provider}/{model}", client))
    if not built:
        _warn(announce, "no jury judges could be built; using the session model")
    return built


def _warn(announce: Callable[[str], None] | None, message: str) -> None:
    text = f"warning: {message}"
    if announce is not None:
        announce(text)
    else:
        print(text, file=sys.stderr)


def _plugins(settings: Settings) -> PluginRegistry | None:
    try:
        return build_registry(settings)
    except SwagError as exc:
        print(f"warning: plugins were not loaded: {exc}", file=sys.stderr)
        return None


def _planner_context(
    goal: str,
    memory: MemoryStore,
    plugins: PluginRegistry | None,
    tracker: TaintTracker | None = None,
    memory_trust: TrustLevel = TrustLevel.TRUSTED,
    *,
    announce: Callable[[str], None] | None = None,
    mode: str = "auto",
) -> str:
    sections: list[str] = []
    if mode != "off":
        items = _recall_items(memory, goal)
        recalled = recall_lines(items)
        if recalled and announce is not None:
            for line in recalled:
                announce(line)
        if recalled:
            sections.append("Relevant memories:\n" + "\n".join(f"- {item}" for item in recalled))
        if tracker is not None:
            for item in items:
                tracker.note(item.content, source="memory", trust=memory_trust)
    skills = _skill_blocks(goal, plugins)
    if skills:
        sections.append("Selected skills:\n\n" + "\n\n".join(body for _name, body in skills))
        if tracker is not None:
            for name, body in skills:
                tracker.note(body, source=f"plugin:{name}", trust=TrustLevel.UNTRUSTED)
    return "\n\n".join(sections)


def _recall_items(memory: MemoryStore, goal: str) -> list[MemoryItem]:
    try:
        return list(memory.search(goal, limit=5))
    except Exception:
        return []


def _skill_blocks(goal: str, plugins: PluginRegistry | None) -> list[tuple[str, str]]:
    if plugins is None:
        return []
    try:
        chosen = plugins.select_skills(goal, limit=5)
    except Exception:
        return []
    blocks: list[tuple[str, str]] = []
    for meta in chosen:
        try:
            body = plugins.load_skill(meta.name).instructions().strip()
        except (KeyError, OSError, SwagError):
            continue
        if body:
            blocks.append((meta.name, f"### {meta.name}\n{body}"))
    return blocks


def _save_summary(
    memory: MemoryStore,
    goal: str,
    summary: str,
    *,
    mode: str,
    prompter: ApprovalPrompter,
    run_id: str,
    announce: Callable[[str], None] | None,
) -> str:
    """Save the run summary. Return the ``remembered:`` line when it was stored."""
    text = summary.strip()
    notice = commit_memory(
        memory,
        text,
        mode=mode,
        prompter=prompter,
        metadata=provenance_metadata(run_id=run_id, kind="run-summary", goal=goal),
    )
    if notice is None:
        return ""
    if notice.saved:
        return notice.text
    if announce is not None:
        announce(notice.text)
    return ""


def _attach_mcp_tools(
    registry: InMemoryToolRegistry,
    settings: Settings,
    policy: PermissionPolicy,
    prompter: ApprovalPrompter,
    plugins: PluginRegistry | None,
    tracker: TaintTracker | None = None,
) -> SwagMCPClient | None:
    servers = _mcp_servers(settings, plugins)
    if not servers:
        return None
    client: SwagMCPClient | None = None
    try:
        client = build_mcp_client(
            settings,
            policy=policy,
            prompter=prompter,
            servers=servers,
            taint=tracker,
        )
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
    """Plugin servers first. An entry in ``$SWAG_HOME/mcp.json`` with the same name wins."""
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
