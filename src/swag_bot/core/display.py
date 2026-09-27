"""Live task list for ``swag run``.

Labels shown in the terminal are pending, running, done, and failed.
``doing`` and ``verifying`` are running. ``skipped`` stays skipped so it is
not confused with a step that ran and failed.
"""

from __future__ import annotations

import threading
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from swag_bot.interfaces import StepStatus, TaskPlan

_LABELS = {
    StepStatus.PENDING: "pending",
    StepStatus.DOING: "running",
    StepStatus.VERIFYING: "running",
    StepStatus.DONE: "done",
    StepStatus.FAILED: "failed",
    StepStatus.SKIPPED: "skipped",
}

_STYLES = {
    "pending": "dim",
    "running": "yellow",
    "done": "green",
    "failed": "red",
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
    """Refresh a task table and print step output underneath it."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(no_color=True)
        self._lock = threading.Lock()
        self._live: Any = None

    def __enter__(self) -> TaskListView:
        try:
            from rich.live import Live

            self._live = Live(
                console=self.console,
                refresh_per_second=8,
                transient=False,
                auto_refresh=False,
            )
            self._live.__enter__()
        except Exception:
            self._live = None
        return self

    def __exit__(self, *exc: object) -> None:
        live: Any = self._live
        self._live = None
        if live is not None:
            live.__exit__(*exc)

    def update(self, plan: TaskPlan) -> None:
        with self._lock:
            table = render_table(plan)
            if self._live is not None:
                self._live.update(table, refresh=True)
            else:
                self.console.print(table)

    def stream(self, text: str) -> None:
        """Print a line of step output that should stay on screen."""
        if not text:
            return
        with self._lock:
            console = self._live.console if self._live is not None else self.console
            console.print(text, highlight=False)
