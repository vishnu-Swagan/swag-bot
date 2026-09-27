"""Plan-do-verify loop.

Dependencies are injected so this module does not import models, safety,
plugins, mcp, or memory. ``swag run`` is the composition root.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swag_bot.core.engine import WorkflowEngine, build_engine
from swag_bot.core.escalation import EscalationController
from swag_bot.core.evidence import EvidenceLedger, current_attempt
from swag_bot.core.executor import StepExecutor
from swag_bot.core.handoff import StepManifest, changed_files, render_handoff, snapshot_text_files
from swag_bot.core.memory_journal import commit_memory, normalize_memory_mode, provenance_metadata
from swag_bot.core.planner import Planner
from swag_bot.core.structured_output import forward_chat
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
    TaintTracker,
    TaskPlan,
    Tool,
    ToolRegistry,
    UndoController,
)
from swag_bot.registry import InMemoryToolRegistry

_TERMINAL_NOTE = {StepStatus.FAILED, StepStatus.SKIPPED}


@dataclass(frozen=True)
class LoopEvent:
    """A progress signal for the CLI or a test.

    ``kind`` is ``plan`` (the plan changed), ``plan_fallback`` (the model
    plan could not be parsed), ``status`` (a step changed), ``output`` (an
    observation), ``tool`` (a tool ran or was denied), or ``memory`` (a
    memory write was saved or declined).
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
        response_format: Mapping[str, Any] | None = None,
    ) -> ChatResponse:
        with self._lock:
            return forward_chat(
                self._inner,
                messages,
                tools=tools,
                model=model,
                response_format=response_format,
            )

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
        strict_plan: bool = False,
        memory_mode: str = "auto",
        action_sink: Callable[[ActionLogEntry], None] | None = None,
        evidence_dir: Path | None = None,
        evidence_enabled: bool = True,
        undo: UndoController | None = None,
        taint: TaintTracker | None = None,
        escalation: EscalationController | None = None,
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
        self.strict_plan = strict_plan
        self.memory_mode = normalize_memory_mode(memory_mode)
        self.action_sink = action_sink
        self.evidence_dir = evidence_dir
        self.evidence_enabled = evidence_enabled
        self.ledger = EvidenceLedger(directory=evidence_dir)
        self.undo = undo
        self.taint = taint
        self.escalation = escalation
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
        self._manifests: dict[str, StepManifest] = {}
        self._remembered: list[str] = []
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
        self._manifests.clear()
        self._remembered.clear()
        self.ledger = EvidenceLedger(directory=self.evidence_dir)

        names = [tool.name for tool in self.tools.list_tools()]
        planner = Planner(
            self._llm,
            model=self.model,
            tool_names=names,
            context=context,
            strict=self.strict_plan,
        )
        plan = planner.create(goal, max_steps=self.max_steps)
        self._plan = plan
        self.ledger.set_run(plan.id, plan.goal)
        if planner.fell_back:
            self._emit(
                LoopEvent(kind="plan_fallback", plan=plan, text=planner.fallback_reason)
            )
        self._emit(LoopEvent(kind="plan", plan=plan))
        if self.escalation is not None:
            self.escalation.bind_goal(goal)
        if dry_run:
            self.summary_text = summarize(self._llm, plan, {}, model=self.model, dry_run=True)
            return plan
        if self.undo is not None:
            self.undo.begin_run(plan.id, self.sandbox.workdir)

        executor = StepExecutor(
            llm=self._llm,
            tools=self.tools,
            policy=self.policy,
            prompter=self.prompter,
            memory=self.memory,
            model=self.model,
            on_action=self._record,
            on_tool=self._on_tool,
            memory_mode=self.memory_mode,
            ledger=self.ledger,
            taint=self.taint,
            escalation=self.escalation,
        )
        verifier = Verifier(
            self._llm,
            model=self.model,
            sandbox=self.sandbox,
            ledger=self.ledger,
            policy=self.policy,
            prompter=self.prompter,
            on_action=self._record,
            grounded=self.evidence_enabled,
        )
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
                remembered=list(self._remembered),
            )
        except Exception:
            self.summary_text = render_record(plan, dict(self.results))
        return plan

    def _execute_step(self, step: Step, executor: StepExecutor, verifier: Verifier) -> None:
        self._local.step_id = step.id
        feedback: str | None = None
        before = snapshot_text_files(self.sandbox.workdir)
        try:
            for attempt in range(1, self.max_attempts + 1):
                token = current_attempt.set(attempt)
                try:
                    stop, feedback = self._gate_step(step, attempt, feedback)
                    if stop:
                        return
                    step.status = StepStatus.DOING
                    self._emit_status(step)
                    if self.undo is not None:
                        self.undo.begin_step(step.id)
                    result = executor.execute(
                        step,
                        attempt=attempt,
                        feedback=feedback,
                        handoff=self._handoff_for(step),
                    )
                    if self.escalation is not None:
                        self.escalation.note_observation(step.id, result.observation)
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
                    if self.escalation is not None:
                        self.escalation.note_verdict(step.id, verdict.passed, verdict.reason)
                    result.evidence_ids = list(verdict.evidence_ids)
                    result.check_results = list(verdict.check_results)
                    if verdict.passed and (verdict.evidence_ids or not self.evidence_enabled):
                        step.status = StepStatus.DONE
                        result.status = StepStatus.DONE
                        result.verified = True
                        self._store(result)
                        self._publish_manifest(step, result, before)
                        self._remember(step, result)
                        self._emit_status(step)
                        return
                    if self.evidence_enabled and (verdict.unverified or verdict.passed):
                        feedback = verdict.reason
                        if attempt >= self.max_attempts:
                            self._unverified(step, result, verdict.reason)
                            self._rollback_step(step.id)
                            return
                        self._rollback_step(step.id)
                        continue
                    feedback = verdict.reason
                    if verdict.replan or attempt >= self.max_attempts:
                        self._fail(step, result, verdict.reason, replan=verdict.replan)
                        self._rollback_step(step.id)
                        return
                    self._rollback_step(step.id)
                finally:
                    current_attempt.reset(token)
        finally:
            self._local.step_id = None

    def _unverified(self, step: Step, result: StepResult, reason: str) -> None:
        step.status = StepStatus.UNVERIFIED
        result.status = StepStatus.UNVERIFIED
        result.error = reason
        result.verified = False
        self._store(result)
        self._emit_status(step)

    def _gate_step(
        self,
        step: Step,
        attempt: int,
        feedback: str | None,
    ) -> tuple[bool, str | None]:
        """Return ``(stop, feedback)``.

        ``stop`` is true only when the user gave no answer to an uncertainty
        question. The step is already marked failed in that case. Feedback
        stays None on a first attempt that does not escalate.
        """
        if self.escalation is None:
            return False, feedback
        estimate = self.escalation.estimate(step, attempt=attempt)
        if not estimate.should_escalate:
            return False, feedback
        self._emit(
            LoopEvent(
                kind="clarify",
                plan=self._require_plan(),
                step_id=step.id,
                text=estimate.question,
            )
        )
        answer = self.escalation.ask(estimate, step)
        if not answer:
            reason = f"Stopped to avoid guessing. {estimate.question}"
            self._fail(
                step,
                StepResult(step_id=step.id, status=StepStatus.FAILED, error=reason),
                reason,
                replan=False,
            )
            return True, feedback
        note = f"The user answered: {answer}\nFollow that answer. Do not guess beyond it."
        if feedback:
            return False, f"{feedback}\n\n{note}"
        return False, note

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

    def _handoff_for(self, step: Step) -> str:
        with self._state_lock:
            manifests = [
                self._manifests[dep] for dep in step.depends_on if dep in self._manifests
            ]
        return render_handoff(manifests)

    def _publish_manifest(self, step: Step, result: StepResult, before: dict[str, str]) -> None:
        after = snapshot_text_files(self.sandbox.workdir)
        files = tuple(changed_files(before, after))
        evidence = _evidence_ids(result, self.ledger, step.id)
        manifest = StepManifest(
            step_id=step.id,
            title=step.title,
            observation=result.observation,
            files=files,
            evidence_ids=evidence,
        )
        with self._state_lock:
            self._manifests[step.id] = manifest

    def _remember(self, step: Step, result: StepResult) -> None:
        if self.memory_mode == "off" or self._plan is None:
            return
        with self._state_lock:
            manifest = self._manifests.get(step.id)
        evidence = manifest.evidence_ids if manifest is not None else tuple(result.evidence_ids)
        notice = commit_memory(
            self.memory,
            f"{step.title}: {result.observation}",
            mode=self.memory_mode,
            prompter=self.prompter,
            metadata=provenance_metadata(
                run_id=self._plan.id,
                kind="step",
                goal=self._plan.goal,
                step_id=step.id,
                evidence_ids=evidence,
            ),
        )
        if notice is None:
            return
        if notice.saved:
            self._remembered.append(notice.text)
        self._emit(
            LoopEvent(
                kind="memory",
                plan=self._require_plan(),
                step_id=step.id,
                text=notice.text,
            )
        )

    def _rollback_step(self, step_id: str) -> None:
        if self.undo is None or not self.undo.auto_rollback:
            return
        self.undo.rollback_step(step_id)

    def _record(self, entry: ActionLogEntry) -> None:
        plan = self._plan
        if plan is not None and entry.run_id is None:
            entry = entry.model_copy(update={"run_id": plan.id})
        with self._log_lock:
            self.action_log.append(entry)
            self.ledger.add_action(entry)
        if self.action_sink is not None:
            self.action_sink(entry)
        if self.undo is not None and entry.approved:
            self.undo.note_action(entry.action, outcome=entry.outcome)

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


def _evidence_ids(result: StepResult, ledger: EvidenceLedger, step_id: str) -> tuple[str, ...]:
    """Ids the next step can cite. Prefer the verdict, then the ledger itself."""
    ids = [item for item in result.evidence_ids if item]
    if ids:
        return tuple(ids)
    return tuple(item.id for item in ledger.for_step(step_id) if item.id)
