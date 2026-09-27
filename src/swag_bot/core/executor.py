"""Run one plan step: model turns, tool calls, permission checks, action log."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from typing import Any

from swag_bot.core.escalation import EscalationController
from swag_bot.core.evidence import EvidenceLedger
from swag_bot.core.memory_journal import label_memory
from swag_bot.core.prompts import EXECUTOR_SYSTEM
from swag_bot.core.redact import redact, redact_known, redact_text
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
    Reversibility,
    RiskLevel,
    Step,
    StepResult,
    StepStatus,
    TaintTracker,
    Tool,
    ToolCall,
    ToolRegistry,
)

_POLICY_KEYS = ("plugin", "permission", "risk_hint")
_HINT_TARGETS = ("url", "path", "selector")

_DESTRUCTIVE = re.compile(r"(?i)\b(rm|rmdir|unlink|shred|mkfs)\b")
_NETWORK = re.compile(r"(?i)\b(curl|wget|ssh|scp|nc|ncat)\b|https?://")

_KIND = {
    "read_file": ActionKind.READ_FILE.value,
    "write_file": ActionKind.WRITE_FILE.value,
    "run_shell": ActionKind.RUN_COMMAND.value,
}

OnAction = Callable[[ActionLogEntry], None]
OnTool = Callable[[str], None]
ToolPicker = Callable[[Step, Sequence[Tool], int, set[str]], Sequence[Tool]]

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
        taint: TaintTracker | None = None,
        escalation: EscalationController | None = None,
        system: str | None = None,
        pick_tools: ToolPicker | None = None,
        guard_repeat_writes: bool = False,
        retry_blank_turns: bool = False,
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
        self.taint = taint
        self.escalation = escalation
        self._step: Step | None = None
        self.system = EXECUTOR_SYSTEM if system is None else system
        self.pick_tools = pick_tools
        self.guard_repeat_writes = guard_repeat_writes
        self.retry_blank_turns = retry_blank_turns
        self._trace_lock = threading.Lock()
        self.traces: dict[str, list[str]] = {}

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
        self._step = step
        try:
            return self._execute(step, attempt=attempt, feedback=feedback, handoff=handoff)
        finally:
            self._step = None
            _current_step.reset(token)

    def _execute(
        self,
        step: Step,
        *,
        attempt: int,
        feedback: str | None,
        handoff: str,
    ) -> StepResult:
        messages: list[Message] = [
            Message.system(self.system),
            Message.user(
                _user_prompt(step, attempt, feedback, self._memories(step), handoff)
            ),
        ]
        observation = ""
        hit_limit = True
        called: set[str] = set()
        for round_index in range(self.max_tool_rounds):
            tool_specs = list(self.tools.list_tools())
            if self.pick_tools is not None:
                tool_specs = list(self.pick_tools(step, tool_specs, round_index, set(called)))
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
                if self.retry_blank_turns and not (message.content or "").strip():
                    messages.append(
                        Message.user("The last reply was empty. Call one tool for this step.")
                    )
                    continue
                hit_limit = False
                break
            for call in message.tool_calls:
                outcome = self._outcome(call, called)
                called.add(call.name)
                self._remember_trace(step.id, call.name, outcome)
                messages.append(Message.tool(call.id, outcome))
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

    def trace_for(self, step_id: str) -> list[str]:
        """Tool outcomes recorded while ``step_id`` ran. Empty if it used no tools."""
        with self._trace_lock:
            return list(self.traces.get(step_id, []))

    def _remember_trace(self, step_id: str, name: str, outcome: str) -> None:
        line = f"{name}: {outcome}"
        with self._trace_lock:
            self.traces.setdefault(step_id, []).append(line)

    def _outcome(self, call: ToolCall, called: set[str]) -> str:
        if self.guard_repeat_writes and call.name == "write_file" and call.name in called:
            return (
                "Already wrote a file in this step. Do not write it again. "
                "Run it if the step says to run it."
            )
        return self._invoke(call)

    def _invoke(self, call: ToolCall) -> str:
        arguments = dict(call.arguments)
        try:
            spec: Tool | None = self.tools.get(call.name)
        except KeyError:
            spec = None
        risk = _initial_risk(call.name, arguments, spec)
        target = _target(call.name, arguments)
        if target is None and spec is not None and (spec.risk_hint or spec.plugin):
            target = _hint_target(arguments)
        summary = redact_text(_summary(call.name, target))
        action = ActionRequest(
            kind=_KIND.get(call.name, ActionKind.TOOL.value),
            summary=summary,
            risk=risk,
            target=target,
            arguments=redact(_policy_arguments(arguments, spec)),
            tool_name=call.name,
        )
        if spec is None:
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

        if self.taint is not None:
            action = self.taint.prepare(action, tool=call.name)

        classified = self.policy.classify(action)
        if action.risk is RiskLevel.DESTRUCTIVE:
            classified = RiskLevel.DESTRUCTIVE
        if classified is not action.risk:
            action = action.model_copy(update={"risk": classified})
        action = _stamp_reversibility(self.policy, action)

        blocked = self._jury_block(action)
        if blocked is not None:
            self._finish(
                call,
                action,
                arguments,
                approved=False,
                approver="jury",
                outcome=blocked,
            )
            self._emit_tool(blocked)
            return blocked

        decision = _apply_taint(_policy_decision(self.policy, action), action)
        if decision == "deny":
            self._finish(
                call,
                action,
                arguments,
                approved=False,
                approver="policy",
                outcome=_log_denial(action),
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
            self._finish(
                call,
                action,
                arguments,
                approved=False,
                approver=approver,
                outcome=_log_denial(action),
            )
            self._emit_tool(_emit_denial(action))
            return _denied_text(action)

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
        if self.taint is not None:
            outcome = self.taint.label_output(call.name, arguments, outcome)
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

    def _jury_block(self, action: ActionRequest) -> str | None:
        """Refuse an irreversible action the jury rejected. None lets it continue.

        Reversible and compensable actions, and runs with escalation off, return
        None so the permission policy is unchanged.
        """
        escalation = self.escalation
        step = self._step
        if escalation is None or step is None:
            return None
        block = escalation.review_action(action, step=step)
        if block is None:
            return None
        return block.reason

    def _emit_tool(self, text: str) -> None:
        if self.on_tool is not None and text:
            self.on_tool(text)


def _stamp_reversibility(policy: PermissionPolicy, action: ActionRequest) -> ActionRequest:
    """Copy ``action`` with ``reversibility`` set when the policy can classify it.

    Policies that do not implement ``reversibility`` leave the field unset.
    The undo ledger classifies again at record time.
    """
    if action.reversibility is not None:
        return action
    method = getattr(policy, "reversibility", None)
    if not callable(method):
        return action
    value = method(action)
    if isinstance(value, Reversibility):
        return action.model_copy(update={"reversibility": value})
    return action


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


def _initial_risk(
    name: str,
    arguments: dict[str, Any],
    spec: Tool | None = None,
) -> RiskLevel:
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
    if spec is not None and spec.risk_hint:
        try:
            return RiskLevel(spec.risk_hint)
        except ValueError:
            return RiskLevel.EXECUTE
    return RiskLevel.EXECUTE


def _policy_arguments(arguments: dict[str, Any], spec: Tool | None) -> dict[str, Any]:
    """Arguments stored on the action. Model-supplied policy keys are dropped."""
    copied = {key: value for key, value in arguments.items() if key not in _POLICY_KEYS}
    if spec is None:
        return copied
    if spec.plugin:
        copied["plugin"] = spec.plugin
    if spec.permission_hint:
        copied["permission"] = spec.permission_hint
    if spec.risk_hint:
        copied["risk_hint"] = spec.risk_hint
    return copied


def _hint_target(arguments: dict[str, Any]) -> str | None:
    for key in _HINT_TARGETS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if len(text) > 180:
                return text[:177] + "..."
            return text
    return None


def _target(name: str, arguments: dict[str, Any]) -> str | None:
    if name in {"read_file", "write_file"}:
        path = arguments.get("path")
        return str(path) if path else None
    if name == "run_shell":
        command = arguments.get("command")
        return str(command) if command else None
    return None


def _summary(name: str, target: str | None) -> str:
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
