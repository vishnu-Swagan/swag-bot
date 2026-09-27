"""Run one plan step: model turns, tool calls, permission checks, action log."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from typing import Any

from swag_bot.core.evidence import EvidenceLedger
from swag_bot.core.memory_journal import label_memory
from swag_bot.core.prompts import EXECUTOR_SYSTEM
from swag_bot.core.redact import redact, redact_known
from swag_bot.interfaces import (
    ActionKind,
    ActionLogEntry,
    ActionRequest,
    ApprovalPrompter,
    AutonomyLevel,
    LLMClient,
    MemoryStore,
    Message,
    PermissionPolicy,
    RiskLevel,
    Step,
    StepResult,
    StepStatus,
    ToolCall,
    ToolRegistry,
)

_DESTRUCTIVE = re.compile(r"(?i)\b(rm|rmdir|unlink|shred|mkfs)\b")
_NETWORK = re.compile(r"(?i)\b(curl|wget|ssh|scp|nc|ncat)\b|https?://")

_KIND = {
    "read_file": ActionKind.READ_FILE.value,
    "write_file": ActionKind.WRITE_FILE.value,
    "run_shell": ActionKind.RUN_COMMAND.value,
}

OnAction = Callable[[ActionLogEntry], None]
OnTool = Callable[[str], None]

# Which step the shared executor is running. Set inside ``execute`` so parallel
# steps do not overwrite each other's id.
_current_step: ContextVar[str] = ContextVar("swag_executor_step", default="")


class StepExecutor:
    """Execute a single step with the injected model, tools, and policy."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        policy: PermissionPolicy,
        prompter: ApprovalPrompter,
        memory: MemoryStore,
        model: str | None = None,
        max_tool_rounds: int = 6,
        on_action: OnAction | None = None,
        on_tool: OnTool | None = None,
        memory_mode: str = "auto",
        ledger: EvidenceLedger | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.policy = policy
        self.prompter = prompter
        self.memory = memory
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.on_action = on_action
        self.on_tool = on_tool
        self.memory_mode = memory_mode
        self.ledger = ledger

    def execute(
        self,
        step: Step,
        *,
        attempt: int,
        feedback: str | None,
        handoff: str = "",
    ) -> StepResult:
        """Run ``step`` once. ``handoff`` is text from the steps this one depends on."""
        token = _current_step.set(step.id)
        try:
            return self._execute(step, attempt=attempt, feedback=feedback, handoff=handoff)
        finally:
            _current_step.reset(token)

    def _execute(
        self,
        step: Step,
        *,
        attempt: int,
        feedback: str | None,
        handoff: str,
    ) -> StepResult:
        tool_specs = list(self.tools.list_tools())
        messages: list[Message] = [
            Message.system(EXECUTOR_SYSTEM),
            Message.user(
                _user_prompt(step, attempt, feedback, self._memories(step), handoff)
            ),
        ]
        observation = ""
        hit_limit = True
        for _ in range(self.max_tool_rounds):
            response = self.llm.chat(
                messages,
                tools=tool_specs or None,
                model=self.model,
            )
            message = response.message
            messages.append(message)
            if message.content:
                observation = message.content
            if not message.tool_calls:
                hit_limit = False
                break
            for call in message.tool_calls:
                messages.append(Message.tool(call.id, self._invoke(call)))
        if hit_limit:
            note = "Stopped after the tool-call limit."
            observation = f"{observation}\n{note}".strip()
        return StepResult(
            step_id=step.id,
            status=StepStatus.VERIFYING,
            observation=observation,
        )

    def _memories(self, step: Step) -> Sequence[str]:
        if self.memory_mode == "off":
            return []
        try:
            hits = self.memory.search(step.title, limit=3)
        except Exception:
            return []
        return [label_memory(item) for item in hits]

    def _invoke(self, call: ToolCall) -> str:
        arguments = dict(call.arguments)
        risk = _initial_risk(call.name, arguments)
        action = ActionRequest(
            kind=_KIND.get(call.name, ActionKind.TOOL.value),
            summary=_summary(call.name, arguments),
            risk=risk,
            target=_target(call.name, arguments),
            arguments=redact(arguments),
        )
        try:
            self.tools.get(call.name)
        except KeyError:
            outcome = f"unknown tool: {call.name}"
            self._finish(
                call,
                action,
                arguments,
                approved=False,
                approver="policy",
                outcome=outcome,
            )
            return outcome

        classified = self.policy.classify(action)
        if action.risk is RiskLevel.DESTRUCTIVE:
            classified = RiskLevel.DESTRUCTIVE
        if classified is not action.risk:
            action = action.model_copy(update={"risk": classified})

        decision = _policy_decision(self.policy, action)
        if decision == "deny":
            outcome = "denied"
            self._finish(
                call,
                action,
                arguments,
                approved=False,
                approver="policy",
                outcome=outcome,
            )
            self._emit_tool(f"denied {action.summary}")
            return "Action denied."
        if decision == "prompt":
            approved = bool(self.prompter.prompt(action))
            approver = "user"
        elif self.policy.autonomy is AutonomyLevel.AUTO:
            approved = True
            approver = "auto"
        else:
            approved = True
            approver = "policy"

        if not approved:
            outcome = "denied"
            self._finish(
                call,
                action,
                arguments,
                approved=False,
                approver=approver,
                outcome=outcome,
            )
            self._emit_tool(f"denied {action.summary}")
            return "Action denied."

        started = time.perf_counter()
        try:
            outcome = self.tools.call(call)
        except Exception as exc:
            outcome = f"error: {exc}"
            self._finish(
                call,
                action,
                arguments,
                approved=True,
                approver=approver,
                outcome=outcome,
                started=started,
            )
            self._emit_tool(outcome)
            return outcome
        self._finish(
            call,
            action,
            arguments,
            approved=True,
            approver=approver,
            outcome=outcome,
            started=started,
        )
        self._emit_tool(action.summary)
        return outcome

    def _finish(
        self,
        call: ToolCall,
        action: ActionRequest,
        arguments: dict[str, Any],
        *,
        approved: bool,
        approver: str,
        outcome: str,
        started: float | None = None,
    ) -> None:
        evidence_id: str | None = None
        step_id = _current_step.get()
        if self.ledger is not None and step_id:
            duration_ms = None if started is None else int((time.perf_counter() - started) * 1000)
            evidence = self.ledger.record_tool(
                step_id=step_id,
                tool=call.name,
                arguments=arguments,
                outcome=outcome,
                approved=approved,
                duration_ms=duration_ms,
            )
            evidence_id = evidence.id
        self._record(
            action,
            arguments,
            approved=approved,
            approver=approver,
            outcome=outcome,
            evidence_id=evidence_id,
        )

    def _record(
        self,
        action: ActionRequest,
        arguments: dict[str, Any],
        *,
        approved: bool,
        approver: str,
        outcome: str,
        evidence_id: str | None = None,
    ) -> None:
        entry = ActionLogEntry(
            action=action,
            autonomy=self.policy.autonomy,
            approved=approved,
            approver=approver,
            outcome=_clip(redact_known(outcome, arguments, action.arguments)),
            evidence_id=evidence_id,
        )
        if self.on_action is not None:
            self.on_action(entry)

    def _emit_tool(self, text: str) -> None:
        if self.on_tool is not None and text:
            self.on_tool(text)


def _policy_decision(policy: PermissionPolicy, action: ActionRequest) -> str:
    """``allow``, ``prompt``, or ``deny``.

    Policies that implement ``decide`` can hard-deny without a prompt.
    Anything else follows ``requires_approval``.
    """
    decide = getattr(policy, "decide", None)
    if callable(decide):
        raw = decide(action)
        value = getattr(raw, "value", raw)
        text = str(value)
        if text in {"allow", "prompt", "deny"}:
            return text
    if policy.requires_approval(action):
        return "prompt"
    return "allow"


def _initial_risk(name: str, arguments: dict[str, Any]) -> RiskLevel:
    if name == "read_file":
        return RiskLevel.READ
    if name == "write_file":
        return RiskLevel.WRITE
    if name == "run_shell":
        command = str(arguments.get("command", ""))
        if _DESTRUCTIVE.search(command):
            return RiskLevel.DESTRUCTIVE
        if _NETWORK.search(command):
            return RiskLevel.NETWORK
        return RiskLevel.EXECUTE
    return RiskLevel.EXECUTE


def _target(name: str, arguments: dict[str, Any]) -> str | None:
    if name in {"read_file", "write_file"}:
        path = arguments.get("path")
        return str(path) if path else None
    if name == "run_shell":
        command = arguments.get("command")
        return str(command) if command else None
    return None


def _summary(name: str, arguments: dict[str, Any]) -> str:
    target = _target(name, arguments)
    if target:
        return f"{name} {target}"
    return name


def _user_prompt(
    step: Step,
    attempt: int,
    feedback: str | None,
    memories: Sequence[str],
    handoff: str = "",
) -> str:
    lines = [
        f"Step id: {step.id}",
        f"Title: {step.title}",
        f"Attempt: {attempt}",
        f"Instruction:\n{step.instruction or step.title}",
    ]
    if handoff.strip():
        lines.append(handoff.strip())
    if memories:
        lines.append("Related memory:")
        lines.extend(f"- {item}" for item in memories)
    if step.checks:
        from swag_bot.core.checks import describe_check

        lines.append("Acceptance checks the harness will run:")
        lines.extend(f"- {describe_check(check)}" for check in step.checks)
    if feedback:
        lines.append(f"The previous attempt did not pass the check: {feedback}")
        lines.append("Try again.")
    return "\n\n".join(lines)


def _clip(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
