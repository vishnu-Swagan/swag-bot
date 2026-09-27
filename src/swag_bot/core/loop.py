"""Plan-do-verify loop.

Dependencies are injected so this module does not import models, safety,
plugins, mcp, or memory. ``swag run`` is the composition root.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from swag_bot.core.engine import WorkflowEngine, build_engine
from swag_bot.core.executor import StepExecutor
from swag_bot.core.planner import Planner
from swag_bot.core.summary import render_record, summarize
from swag_bot.core.tools import register_builtin_tools
from swag_bot.core.verifier import Verifier
from swag_bot.interfaces import (
    ActionLogEntry,
    ApprovalPrompter,
    ChatResponse,
    LLMClient,
    MemoryStore,
    Message,
    PermissionPolicy,
    Sandbox,
    Step,
    StepResult,
    StepStatus,
    TaskPlan,
    Tool,
    ToolRegistry,
)
from swag_bot.registry import InMemoryToolRegistry

_TERMINAL_NOTE = {StepStatus.FAILED, StepStatus.SKIPPED}


@dataclass(frozen=True)
class LoopEvent:
    """A progress signal for the CLI or a test.

    ``kind`` is ``plan`` (the plan changed), ``status`` (a step changed),
    ``output`` (an observation), or ``tool`` (a tool ran or was denied).
    """

    kind: str
    plan: TaskPlan
    step_id: str | None = None
    status: str | None = None
    text: str = ""


class _LockedLLM:
    """Serialize chat calls. Step tools still run outside the lock."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self._lock = threading.Lock()

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        with self._lock:
            return self._inner.chat(messages, tools=tools, model=model)

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        with self._lock:
            return self._inner.complete(prompt, model=model)


class PlanDoVerifyLoop:
    """Turn a goal into a ``TaskPlan``, run each step, and verify it.

    Independent steps run together up to ``concurrency``. A failed check is
    retried until ``max_attempts``. When the verifier asks for a new approach,
    the planner appends replacement steps, still capped by ``max_steps``.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        sandbox: Sandbox,
        memory: MemoryStore,
        policy: PermissionPolicy,
        prompter: ApprovalPrompter,
        tools: ToolRegistry | None = None,
        model: str | None = None,
        max_steps: int = 8,
        max_attempts: int = 2,
        concurrency: int = 4,
        engine: str = "python",
        graphbit_module: object | None = None,
        on_event: Callable[[LoopEvent], None] | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.llm = llm
        self.sandbox = sandbox
        self.memory = memory
        self.policy = policy
        self.prompter = prompter
        self.model = model
        self.max_steps = max_steps
        self.max_attempts = max_attempts
        self.concurrency = concurrency
        self.on_event = on_event
        if tools is None:
            tools = InMemoryToolRegistry()
        register_builtin_tools(tools, sandbox)
        self.tools = tools
        selected, note = build_engine(engine, module=graphbit_module)
        self.engine: WorkflowEngine = selected
        self.engine_note = note
        self.action_log: list[ActionLogEntry] = []
        self.results: dict[str, StepResult] = {}
        self.summary_text = ""
        self._llm = _LockedLLM(llm)
        self._plan: TaskPlan | None = None
        self._notes: dict[str, str] = {}
        self._replan_requests: list[tuple[Step, str]] = []
        self._replans = 0
        self._log_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._emit_lock = threading.Lock()
        self._local = threading.local()

    def run(self, goal: str, *, dry_run: bool = False, context: str = "") -> TaskPlan:
        """Plan, do, and verify ``goal``. A dry run returns the plan unexecuted.

        ``context`` is extra planner text from the composition root: recalled
        memories and the instructions of skills selected for this goal.
        """
        with self._log_lock:
            self.action_log.clear()
        with self._state_lock:
            self.results.clear()
            self._replan_requests.clear()
        self.summary_text = ""
        self._notes.clear()
        self._replans = 0
        self._plan = None

        names = [tool.name for tool in self.tools.list_tools()]
        planner = Planner(self._llm, model=self.model, tool_names=names, context=context)
        plan = planner.create(goal, max_steps=self.max_steps)
        self._plan = plan
        self._emit(LoopEvent(kind="plan", plan=plan))
        if dry_run:
            self.summary_text = summarize(self._llm, plan, {}, model=self.model, dry_run=True)
            return plan

        executor = StepExecutor(
            llm=self._llm,
            tools=self.tools,
            policy=self.policy,
            prompter=self.prompter,
            memory=self.memory,
            model=self.model,
            on_action=self._record,
            on_tool=self._on_tool,
        )
        verifier = Verifier(self._llm, model=self.model)
        while True:
            self.engine.run(
                plan,
                lambda step: self._execute_step(step, executor, verifier),
                concurrency=self.concurrency,
                notes=self._notes,
                on_status=self._on_engine_status,
            )
            if not self._apply_replan(plan, planner):
                break
        try:
            self.summary_text = summarize(
                self._llm,
                plan,
                dict(self.results),
                model=self.model,
                dry_run=False,
            )
        except Exception:
            self.summary_text = render_record(plan, dict(self.results))
        return plan

    def _execute_step(self, step: Step, executor: StepExecutor, verifier: Verifier) -> None:
        self._local.step_id = step.id
        feedback: str | None = None
        try:
            for attempt in range(1, self.max_attempts + 1):
                step.status = StepStatus.DOING
                self._emit_status(step)
                result = executor.execute(step, attempt=attempt, feedback=feedback)
                if result.observation:
                    self._emit(
                        LoopEvent(
                            kind="output",
                            plan=self._require_plan(),
                            step_id=step.id,
                            text=result.observation,
                        )
                    )
                step.status = StepStatus.VERIFYING
                self._emit_status(step)
                verdict = verifier.check(step, result)
                if verdict.passed:
                    step.status = StepStatus.DONE
                    result.status = StepStatus.DONE
                    result.verified = True
                    self._store(result)
                    self._remember(step, result)
                    self._emit_status(step)
                    return
                feedback = verdict.reason
                if verdict.replan or attempt >= self.max_attempts:
                    self._fail(step, result, verdict.reason, replan=verdict.replan)
                    return
        finally:
            self._local.step_id = None

    def _fail(self, step: Step, result: StepResult, reason: str, *, replan: bool) -> None:
        step.status = StepStatus.FAILED
        result.status = StepStatus.FAILED
        result.error = reason
        result.verified = False
        self._store(result)
        if replan:
            with self._state_lock:
                self._replan_requests.append((step, reason))
        self._emit_status(step)

    def _apply_replan(self, plan: TaskPlan, planner: Planner) -> bool:
        with self._state_lock:
            requests = list(self._replan_requests)
            self._replan_requests.clear()
        if not requests or self._replans >= self.max_attempts:
            return False
        room = self.max_steps - len(plan.steps)
        if room <= 0:
            return False
        self._replans += 1
        new_steps = planner.revise(plan, requests, max_new=room)
        if not new_steps:
            return False
        done_ids = {step.id for step in plan.steps if step.status == StepStatus.DONE}
        new_ids = {step.id for step in new_steps}
        for step in new_steps:
            step.depends_on = [
                dep for dep in step.depends_on if dep in done_ids or dep in new_ids
            ]
        plan.steps.extend(new_steps)
        self._emit(LoopEvent(kind="plan", plan=plan))
        return True

    def _on_engine_status(self, step: Step) -> None:
        if step.status in _TERMINAL_NOTE and step.id not in self.results:
            reason = self._notes.get(step.id, "")
            self._store(
                StepResult(
                    step_id=step.id,
                    status=step.status,
                    observation=reason,
                    error=reason or None,
                    verified=False,
                )
            )
        self._emit_status(step)

    def _remember(self, step: Step, result: StepResult) -> None:
        try:
            self.memory.add(
                f"{step.title}: {result.observation}",
                metadata={"step_id": step.id},
            )
        except Exception:
            # The step already passed. A memory outage should not undo that.
            return

    def _record(self, entry: ActionLogEntry) -> None:
        with self._log_lock:
            self.action_log.append(entry)

    def _on_tool(self, text: str) -> None:
        step_id = getattr(self._local, "step_id", None)
        self._emit(
            LoopEvent(
                kind="tool",
                plan=self._require_plan(),
                step_id=step_id if isinstance(step_id, str) else None,
                text=text,
            )
        )

    def _store(self, result: StepResult) -> None:
        with self._state_lock:
            self.results[result.step_id] = result

    def _emit_status(self, step: Step) -> None:
        self._emit(
            LoopEvent(
                kind="status",
                plan=self._require_plan(),
                step_id=step.id,
                status=step.status.value,
            )
        )

    def _emit(self, event: LoopEvent) -> None:
        if self.on_event is None:
            return
        with self._emit_lock:
            self.on_event(event)

    def _require_plan(self) -> TaskPlan:
        if self._plan is None:
            raise RuntimeError("the loop has no plan yet")
        return self._plan
