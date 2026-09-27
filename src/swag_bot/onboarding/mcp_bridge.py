"""Register Swag Bot's MCP tools and bind the approval prompter.

Imported only after the optional ``mcp`` package is known to be installed.
Approvals use MCP elicitation when the client declares form support. The
Python SDK sends that as ``elicitation/create`` on the 2025 handshake and as
an ``InputRequiredResult`` on protocol 2026-07-28. Clients that declare
neither get a denial string in the tool result. Nothing here writes to
stdout or reads stdin.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Annotated, Any, cast

import anyio

from swag_bot.interfaces import AutonomyLevel
from swag_bot.onboarding.approvals import (
    AllowRisky,
    ApprovalReason,
    MCPApprovalPrompter,
    McpApprovals,
    TaskDecision,
    bind_prompter,
    load_mcp_approvals,
    reset_prompter,
)
from swag_bot.onboarding.status import doctor_report
from swag_bot.onboarding.tasks import BOARD

try:
    from mcp.server.elicitation import (
        AcceptedElicitation,
        CancelledElicitation,
        DeclinedElicitation,
        ElicitationResult,
    )
    from mcp.server.mcpserver.context import Context
    from mcp.server.mcpserver.resolve import Elicit, Resolve
except ImportError as exc:  # pragma: no cover - caller checks the extra first
    raise ImportError("mcp is required to register Swag Bot's MCP tools") from exc

TaskRunner = Callable[[str], str]
SkillProvider = Callable[[], Sequence[Any]]
_RISKY_COVERED = frozenset({"write", "execute", "network"})


def resolve_task_approval(goal: str, ctx: Context) -> Elicit[AllowRisky] | TaskDecision:
    """Ask once per task, or skip the form when it cannot be delivered.

    The parameter name ``goal`` is the tool argument. ``ctx`` is injected
    by the SDK. Returning ``Elicit`` is what triggers the form. Returning
    ``TaskDecision`` does not send a request.
    """
    if not goal or not str(goal).strip():
        return TaskDecision(allow_risky=False, reason="empty")
    from swag_bot.config import load_settings

    settings = load_settings()
    grants = load_mcp_approvals()
    if settings.autonomy is AutonomyLevel.AUTO or _covers_risky(grants):
        if settings.autonomy is AutonomyLevel.AUTO:
            reason: ApprovalReason = "auto"
        else:
            reason = "preapproved"
        return TaskDecision(allow_risky=True, reason=reason)
    if not _supports_form(ctx):
        return TaskDecision(allow_risky=False, reason="unsupported")
    short = " ".join(str(goal).split())
    if len(short) > 180:
        short = short[:177] + "..."
    message = (
        "Swag Bot is about to run a task that may write files or run shell "
        f"commands: {short}. Allow those actions? Destructive actions stay denied."
    )
    return Elicit(message, AllowRisky)


def register_tools(
    server: Any,
    *,
    runner: TaskRunner | None,
    skills_provider: SkillProvider | None,
) -> None:
    """Attach the Swag Bot tools to an ``MCPServer``."""

    @_tool(server, description="Run a Swag Bot task. Pass the goal; the result is a short summary.")
    async def swag_run_task(
        goal: str,
        ctx: Context,
        approval: Annotated[ElicitationResult[AllowRisky], Resolve(resolve_task_approval)],
    ) -> str:
        """Run a goal. Approvals use MCP elicitation or a preapproved grant."""
        del ctx
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")
        if runner is None:
            return "No task runner is configured."
        prompter = prompter_for(approval)

        def run_bound() -> str:
            # Bind inside the worker. The prompter must be visible on the
            # thread that calls it, not only on the event-loop task.
            token = bind_prompter(prompter)
            try:
                return runner(goal)
            finally:
                reset_prompter(token)

        try:
            summary = await anyio.to_thread.run_sync(run_bound)
        except Exception as exc:
            summary = str(exc)
        return _with_denials(summary if isinstance(summary, str) else json.dumps(summary), prompter)

    @_tool(
        server,
        description=(
            "Start a Swag Bot task and return a run_id. Poll swag_task_status "
            "and swag_task_result so a long run does not hit the client timeout."
        ),
    )
    async def swag_start_task(
        goal: str,
        ctx: Context,
        approval: Annotated[ElicitationResult[AllowRisky], Resolve(resolve_task_approval)],
    ) -> str:
        """Start a goal in the background and return ``{"run_id": ...}``."""
        del ctx
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")
        if runner is None:
            return "No task runner is configured."
        prompter = prompter_for(approval)
        run_id = BOARD.start(goal, runner, prompter)
        return json.dumps({"run_id": run_id, "status": "running"})

    @_tool(server, description="Status of a task started with swag_start_task.")
    def swag_task_status(run_id: str) -> str:
        """Return status, summary, and any approval denials for ``run_id``."""
        return _task_json(run_id)

    @_tool(server, description="Result of a task started with swag_start_task.")
    def swag_task_result(run_id: str) -> str:
        """Return the same snapshot as swag_task_status."""
        return _task_json(run_id)

    @_tool(server, description="List Agent Skills (name and description).")
    def swag_list_skills() -> str:
        """List Agent Skills as a JSON array of name and description."""
        if skills_provider is None:
            return "[]"
        return json.dumps([_skill_row(item) for item in skills_provider()])

    @_tool(server, description="Setup and doctor status as JSON. Does not print secrets.")
    def swag_setup_status() -> str:
        """Return the same JSON object as ``swag doctor --json``."""
        return json.dumps(doctor_report())


def prompter_for(outcome: Any) -> MCPApprovalPrompter:
    """Build the prompter for one resolved approval."""
    grants = load_mcp_approvals()
    if isinstance(outcome, (DeclinedElicitation, CancelledElicitation)):
        return MCPApprovalPrompter(allow_risky=False, reason="declined", grants=grants)
    data: Any = outcome.data if isinstance(outcome, AcceptedElicitation) else outcome
    if isinstance(data, TaskDecision):
        return MCPApprovalPrompter(allow_risky=data.allow_risky, reason=data.reason, grants=grants)
    if isinstance(data, AllowRisky):
        allowed = bool(data.allow)
        return MCPApprovalPrompter(
            allow_risky=allowed,
            reason="elicited" if allowed else "declined",
            grants=grants,
        )
    return MCPApprovalPrompter(allow_risky=False, reason="unsupported", grants=grants)


def _covers_risky(grants: McpApprovals) -> bool:
    held = set(grants.risks)
    return _RISKY_COVERED <= held


def _supports_form(ctx: Any) -> bool:
    capabilities = getattr(ctx, "client_capabilities", None)
    elicitation = getattr(capabilities, "elicitation", None)
    if elicitation is None:
        return False
    form = getattr(elicitation, "form", None)
    url = getattr(elicitation, "url", None)
    # A bare ``elicitation: {}`` (form and url both absent) counts as form support.
    return form is not None or url is None


def _with_denials(summary: str, prompter: MCPApprovalPrompter) -> str:
    extra = prompter.explain().strip()
    if not extra:
        return summary
    if summary.strip():
        return summary.rstrip() + "\n\n" + extra
    return extra


def _task_json(run_id: str) -> str:
    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be empty")
    view = BOARD.get(run_id.strip())
    if view is None:
        return json.dumps({"error": "unknown run_id", "run_id": run_id})
    return json.dumps(
        {
            "run_id": view.run_id,
            "status": view.status,
            "summary": view.summary,
            "denials": view.denials,
        }
    )


def _skill_row(item: Any) -> dict[str, str]:
    if isinstance(item, dict):
        return {
            "name": str(item.get("name", "")),
            "description": str(item.get("description", "")),
        }
    meta = getattr(item, "meta", None)
    if meta is not None:
        return {
            "name": str(getattr(meta, "name", "")),
            "description": str(getattr(meta, "description", "")),
        }
    return {
        "name": str(getattr(item, "name", "")),
        "description": str(getattr(item, "description", "")),
    }


def _tool(server: Any, *, description: str) -> Callable[[Any], Any]:
    decorator = server.tool(description=description)
    return cast(Callable[[Any], Any], decorator)
