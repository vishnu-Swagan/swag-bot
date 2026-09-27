"""Schedule plan steps.

The default engine is pure Python and uses asyncio. Independent steps run at
the same time, up to a concurrency limit. A step waits until every step it
depends on is done. GraphBit, when requested and installed, validates the same
graph and then uses this scheduler so tool permissions stay in Swag Bot.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from swag_bot.interfaces import Step, StepStatus, TaskPlan

Worker = Callable[[Step], None]
StatusCallback = Callable[[Step], None]

_TERMINAL = {StepStatus.DONE, StepStatus.FAILED, StepStatus.UNVERIFIED, StepStatus.SKIPPED}
_BLOCKING = {StepStatus.FAILED, StepStatus.UNVERIFIED, StepStatus.SKIPPED}


class WorkflowEngine(Protocol):
    """Run the pending steps of a plan."""

    name: str

    def run(
        self,
        plan: TaskPlan,
        worker: Worker,
        *,
        concurrency: int,
        notes: dict[str, str],
        on_status: StatusCallback | None = None,
    ) -> None:
        """Execute ``worker`` for each ready step.

        ``worker`` must set the step status to a terminal value. ``notes``
        receives a short reason when this engine skips or fails a step itself.
        """
        ...


class PythonWorkflowEngine:
    """Dependency-aware asyncio scheduler. This is the default engine."""

    name = "python"

    def run(
        self,
        plan: TaskPlan,
        worker: Worker,
        *,
        concurrency: int,
        notes: dict[str, str],
        on_status: StatusCallback | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        _run_blocking(
            lambda: self._execute(
                plan,
                worker,
                concurrency=concurrency,
                notes=notes,
                on_status=on_status,
            )
        )

    async def _execute(
        self,
        plan: TaskPlan,
        worker: Worker,
        *,
        concurrency: int,
        notes: dict[str, str],
        on_status: StatusCallback | None,
    ) -> None:
        semaphore = asyncio.Semaphore(concurrency)
        by_id = {step.id: step for step in plan.steps}
        inflight: dict[str, asyncio.Task[None]] = {}
        claimed: set[str] = set()

        async def launch(step: Step) -> None:
            async with semaphore:
                try:
                    await asyncio.to_thread(worker, step)
                except Exception as exc:
                    step.status = StepStatus.FAILED
                    notes[step.id] = f"{type(exc).__name__}: {exc}"
                    if on_status is not None:
                        on_status(step)

        while True:
            progressed = False
            for step in plan.steps:
                if step.status != StepStatus.PENDING or step.id in claimed:
                    continue
                deps = [by_id[dep] for dep in step.depends_on]
                if any(dep.status in _BLOCKING for dep in deps):
                    step.status = StepStatus.SKIPPED
                    notes[step.id] = (
                        "Skipped because a dependency failed, was skipped, or was unverified."
                    )
                    progressed = True
                    if on_status is not None:
                        on_status(step)
                    continue
                if all(dep.status == StepStatus.DONE for dep in deps):
                    claimed.add(step.id)
                    inflight[step.id] = asyncio.create_task(launch(step))
                    progressed = True

            if inflight:
                finished, _pending = await asyncio.wait(
                    set(inflight.values()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                finished_ids = [sid for sid, task in inflight.items() if task in finished]
                for sid in finished_ids:
                    task = inflight.pop(sid)
                    error = task.exception()
                    if error is not None:
                        by_id[sid].status = StepStatus.FAILED
                        notes.setdefault(sid, f"{type(error).__name__}: {error}")
                        if on_status is not None:
                            on_status(by_id[sid])
                    elif by_id[sid].status not in _TERMINAL:
                        by_id[sid].status = StepStatus.FAILED
                        notes[sid] = "The step did not finish."
                        if on_status is not None:
                            on_status(by_id[sid])
                continue

            if progressed:
                continue

            pending = [step for step in plan.steps if step.status == StepStatus.PENDING]
            for step in pending:
                step.status = StepStatus.FAILED
                notes[step.id] = "Dependency cycle."
                if on_status is not None:
                    on_status(step)
            return


def build_engine(name: str = "python", *, module: Any | None = None) -> tuple[WorkflowEngine, str]:
    """Select an engine.

    ``python`` is the default. ``graphbit`` uses GraphBit when the optional
    extra is installed and otherwise falls back to Python. ``auto`` uses
    GraphBit only when it is already importable.
    """
    requested = (name or "python").strip().lower()
    if requested == "python":
        return PythonWorkflowEngine(), ""
    if requested not in {"graphbit", "auto"}:
        raise ValueError(f"unknown workflow engine: {name}")
    from swag_bot.core.graphbit import GraphBitWorkflowEngine, graphbit_available

    if module is None and not graphbit_available():
        note = ""
        if requested == "graphbit":
            note = "GraphBit is not installed; using the Python engine."
        return PythonWorkflowEngine(), note
    return GraphBitWorkflowEngine(module=module), ""


def _run_blocking(factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run ``factory()`` on an asyncio loop.

    ``AgentLoop.run`` is synchronous. When a loop is already running, the
    scheduler moves to a helper thread so ``asyncio.run`` still works.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(factory())
        return
    box: dict[str, BaseException] = {}

    def _target() -> None:
        try:
            asyncio.run(factory())
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=_target, name="swag-engine")
    thread.start()
    thread.join()
    error = box.get("error")
    if error is not None:
        raise error
