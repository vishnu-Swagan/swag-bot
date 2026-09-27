"""Run one plan step: model turns, tool calls, permission checks, action log."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from swag_bot.core.prompts import EXECUTOR_SYSTEM
from swag_bot.core.redact import redact, redact_known
from swag_bot.interfaces import (
    SWAG_TAINT_KEY,
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
    TaintTracker,
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
        taint: TaintTracker | None = None,
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
        self.taint = taint

    def execute(self, step: Step, *, attempt: int, feedback: str | None) -> StepResult:
        """Run ``step`` once. The caller verifies the returned observation."""
        tool_specs = list(self.tools.list_tools())
        messages: list[Message] = [
            Message.system(EXECUTOR_SYSTEM),
            Message.user(_user_prompt(step, attempt, feedback, self._memories(step))),
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
        try:
            hits = self.memory.search(step.title, limit=3)
        except Exception:
            return []
        return [item.content for item in hits]

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
            self._record(action, arguments, approved=False, approver="policy", outcome=outcome)
            return outcome

        if self.taint is not None:
            action = self.taint.prepare(action, tool=call.name)

        classified = self.policy.classify(action)
        if action.risk is RiskLevel.DESTRUCTIVE:
            classified = RiskLevel.DESTRUCTIVE
        if classified is not action.risk:
            action = action.model_copy(update={"risk": classified})

        decision = _apply_taint(_policy_decision(self.policy, action), action)
        if decision == "deny":
            self._record(
                action, arguments, approved=False, approver="policy", outcome=_log_denial(action)
            )
            self._emit_tool(_emit_denial(action))
            return _denied_text(action)
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
            self._record(
                action, arguments, approved=False, approver=approver, outcome=_log_denial(action)
            )
            self._emit_tool(_emit_denial(action))
            return _denied_text(action)

        try:
            outcome = self.tools.call(call)
        except Exception as exc:
            outcome = f"error: {exc}"
            self._record(action, arguments, approved=True, approver=approver, outcome=outcome)
            self._emit_tool(outcome)
            return outcome
        self._record(action, arguments, approved=True, approver=approver, outcome=outcome)
        self._emit_tool(action.summary)
        if self.taint is not None:
            outcome = self.taint.label_output(call.name, arguments, outcome)
        return outcome

    def _record(
        self,
        action: ActionRequest,
        arguments: dict[str, Any],
        *,
        approved: bool,
        approver: str,
        outcome: str,
    ) -> None:
        entry = ActionLogEntry(
            action=action,
            autonomy=self.policy.autonomy,
            approved=approved,
            approver=approver,
            outcome=_clip(redact_known(outcome, arguments, action.arguments)),
        )
        if self.on_action is not None:
            self.on_action(entry)

    def _emit_tool(self, text: str) -> None:
        if self.on_tool is not None and text:
            self.on_tool(text)


def _apply_taint(decision: str, action: ActionRequest) -> str:
    """Honor a taint stamp even when the policy does not read it.

    A deny stays a deny. A tainted sink upgrades an allow into a prompt, or
    any decision into a deny when the stamp says to block.
    """
    raw = action.arguments.get(SWAG_TAINT_KEY)
    if not isinstance(raw, dict) or raw.get("tainted") is not True:
        return decision
    enforcement = raw.get("enforcement")
    if enforcement == "deny":
        return "deny"
    if enforcement == "prompt" and decision == "allow":
        return "prompt"
    return decision


def _taint_message(action: ActionRequest) -> str | None:
    raw = action.arguments.get(SWAG_TAINT_KEY)
    if not isinstance(raw, dict) or raw.get("tainted") is not True:
        return None
    message = raw.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return None


def _denied_text(action: ActionRequest) -> str:
    """Text returned to the model. Untainted denials keep the old sentence."""
    return _taint_message(action) or "Action denied."


def _log_denial(action: ActionRequest) -> str:
    """Action-log outcome. Untainted denials stay the single word ``denied``."""
    return _taint_message(action) or "denied"


def _emit_denial(action: ActionRequest) -> str:
    message = _taint_message(action)
    if message:
        return message
    return f"denied {action.summary}"


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


def _user_prompt(step: Step, attempt: int, feedback: str | None, memories: Sequence[str]) -> str:
    lines = [
        f"Step id: {step.id}",
        f"Title: {step.title}",
        f"Attempt: {attempt}",
        f"Instruction:\n{step.instruction or step.title}",
    ]
    if memories:
        lines.append("Related memory:")
        lines.extend(f"- {item}" for item in memories)
    if feedback:
        lines.append(f"The previous attempt did not pass the check: {feedback}")
        lines.append("Try again.")
    return "\n\n".join(lines)


def _clip(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
