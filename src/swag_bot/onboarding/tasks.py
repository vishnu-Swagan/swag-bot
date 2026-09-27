"""In-process task board for long MCP runs.

``swag_start_task`` returns immediately so the client does not time out.
Status and result are polled. The worker thread binds the MCP prompter
itself; it does not read stdin.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from swag_bot.onboarding.approvals import MCPApprovalPrompter, bind_prompter, reset_prompter

Runner = Callable[[str], str]


@dataclass
class TaskView:
    """Public snapshot of one background task."""

    run_id: str
    status: str
    summary: str
    denials: str


class TaskBoard:
    """Thread-safe map of run id to task state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskView] = {}

    def start(self, goal: str, runner: Runner, prompter: MCPApprovalPrompter) -> str:
        """Start ``runner`` on a daemon thread and return the run id."""
        run_id = uuid4().hex
        view = TaskView(run_id=run_id, status="running", summary="", denials="")
        with self._lock:
            self._tasks[run_id] = view

        def worker() -> None:
            token = bind_prompter(prompter)
            summary = ""
            status = "done"
            try:
                summary = runner(goal)
            except Exception as exc:
                summary = str(exc)
                status = "error"
            finally:
                reset_prompter(token)
            finished = TaskView(
                run_id=run_id,
                status=status,
                summary=summary,
                denials=prompter.explain(),
            )
            with self._lock:
                self._tasks[run_id] = finished

        threading.Thread(target=worker, name=f"swag-mcp-{run_id[:8]}", daemon=True).start()
        return run_id

    def get(self, run_id: str) -> TaskView | None:
        """Return a snapshot, or None when ``run_id`` is unknown."""
        with self._lock:
            view = self._tasks.get(run_id)
            if view is None:
                return None
            return TaskView(view.run_id, view.status, view.summary, view.denials)

    def reset(self) -> None:
        """Drop every task. Tests use this between cases."""
        with self._lock:
            self._tasks.clear()


BOARD = TaskBoard()
