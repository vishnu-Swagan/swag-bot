"""Live task list for ``swag run``.

Labels shown in the terminal are pending, running, done, and failed.
``doing`` and ``verifying`` are running. ``skipped`` stays skipped so it is
not confused with a step that ran and failed.

The live table is transient and is stopped while a person answers a prompt.
Leaving it running paints the next refresh over the approval panel and drops
broken copies into the scrollback. Progress lines are printed once, with
Rich markup off, so a prefix like ``[step-1]`` stays visible.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from swag_bot.core.loop import LoopEvent
from swag_bot.core.summary import plain_terminal
from swag_bot.interfaces import ApprovalPrompter, StepStatus, TaskPlan

_LABELS = {
    StepStatus.PENDING: "pending",
    StepStatus.DOING: "running",
    StepStatus.VERIFYING: "running",
    StepStatus.DONE: "done",
    StepStatus.FAILED: "failed",
    StepStatus.UNVERIFIED: "unverified",
    StepStatus.SKIPPED: "skipped",
}

_STYLES = {
    "pending": "dim",
    "running": "yellow",
    "done": "green",
    "failed": "red",
    "unverified": "yellow",
    "skipped": "magenta",
}


def display_status(status: StepStatus) -> str:
    """Map a step status to the word shown in the live task list."""
    return _LABELS.get(status, status.value)


def render_table(plan: TaskPlan) -> Table:
    """A rich table of the current plan."""
    table = Table(title="Tasks", expand=True)
    table.add_column("id", no_wrap=True)
    table.add_column("title")
    table.add_column("status", no_wrap=True)
    for step in plan.steps:
        label = display_status(step.status)
        table.add_row(step.id, step.title, Text(label, style=_STYLES.get(label, "")))
    return table


class TaskListView:
    """Refresh one task table on a terminal, and print each progress line once."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(no_color=True, highlight=False)
        self._lock = threading.Lock()
        self._live: Any = None
        self._plan: TaskPlan | None = None
        self._depth = 0

    def __enter__(self) -> TaskListView:
        self._start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop()

    def update(self, plan: TaskPlan) -> None:
        """Remember ``plan`` and redraw the live table when one is on screen."""
        with self._lock:
            self._plan = plan
            live = self._live if self._depth == 0 else None
        if live is not None:
            live.update(render_table(plan), refresh=True)

    def note(self, text: str) -> None:
        """Print one durable line. Markup is off so ``[step-id]`` is literal.

        The live table is stopped first. Printing through it paints a second
        copy of the line and leaves stacked header fragments in the scrollback.
        """
        if not text:
            return
        with self._lock:
            suspend = self._live is not None and self._depth == 0
        if suspend:
            self._stop()
        self.console.print(plain_terminal(text), highlight=False, markup=False)
        if suspend:
            self._start()
            self._refresh()

    def stream(self, text: str) -> None:
        """Alias of ``note`` kept for callers that still say stream."""
        self.note(text)

    def print_final(self) -> None:
        """Print the task table once after the live view has stopped."""
        with self._lock:
            plan = self._plan
        if plan is not None:
            self.console.print(render_table(plan))

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Stop the live table so a prompt can use the terminal, then restore it."""
        with self._lock:
            self._depth += 1
            stop = self._depth == 1
        if stop:
            self._stop()
        try:
            yield
        finally:
            with self._lock:
                self._depth -= 1
                start = self._depth == 0
            if start:
                self._start()
                self._refresh()

    def _use_live(self) -> bool:
        return bool(self.console.is_terminal)

    def _start(self) -> None:
        if self._live is not None or not self._use_live():
            return
        try:
            from rich.live import Live

            live = Live(
                console=self.console,
                refresh_per_second=4,
                transient=True,
                auto_refresh=False,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            live.__enter__()
        except Exception:
            self._live = None
            return
        self._live = live

    def _stop(self) -> None:
        with self._lock:
            live = self._live
            self._live = None
        if live is not None:
            live.__exit__(None, None, None)

    def _refresh(self) -> None:
        with self._lock:
            plan = self._plan
            live = self._live
        if plan is not None and live is not None:
            live.update(render_table(plan), refresh=True)

    @staticmethod
    def _print(live: Any, console: Console, text: str) -> None:
        shown = plain_terminal(text)
        if live is not None:
            live.console.print(shown, highlight=False, markup=False)
            return
        console.print(shown, highlight=False, markup=False)


class RunProgress:
    """Turn loop events into one status line each. No second copy via ``typer.echo``."""

    def __init__(self, view: TaskListView) -> None:
        self.view = view
        self.shown: dict[str, str] = {}

    def __call__(self, event: LoopEvent) -> None:
        if event.kind == "plan_fallback":
            reason = event.text or "the model did not return a readable plan"
            self.view.note(
                "PLAN FALLBACK: "
                + reason
                + ". Continuing with a single step taken from the goal."
                + " Pass --strict-plan to exit instead of falling back."
            )
            return
        if event.kind == "memory" and event.text:
            self.view.note(event.text)
            return
        if event.kind in {"plan", "status"}:
            self.view.update(event.plan)
            for step in event.plan.steps:
                if event.kind == "status" and event.step_id not in {None, step.id}:
                    continue
                label = display_status(step.status)
                if self.shown.get(step.id) == label:
                    continue
                self.shown[step.id] = label
                self.view.note(f"[{label}] {step.id} {step.title}")
            return
        if event.text:
            prefix = f"[{event.step_id}] " if event.step_id else ""
            self.view.note(f"{prefix}{event.text}")


class PromptSuspender:
    """Pause the live task list while ``inner`` asks for approval."""

    def __init__(self, inner: ApprovalPrompter, view: TaskListView) -> None:
        self._inner = inner
        self._view = view

    def prompt(self, action: Any) -> bool:
        with self._view.suspended():
            allowed = bool(self._inner.prompt(action))
            # End the question line so the next progress line cannot continue it.
            self._view.console.print()
            return allowed
