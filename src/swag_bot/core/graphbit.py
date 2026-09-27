"""Optional GraphBit workflow backend.

GraphBit (InfinitiBit/graphbit, Apache-2.0) is an optional extra::

    pip install -e ".[graphbit]"

It is imported only when a caller asks for it. The pure-Python engine remains
the default. GraphBit builds and validates the dependency graph. Step bodies
still run through Swag Bot's worker so the permission policy, the action log,
and the injected model stay in this process. GraphBit's own executor calls a
provider model directly, which would skip those checks.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any

from swag_bot.core.engine import StatusCallback, Worker
from swag_bot.errors import SwagError
from swag_bot.interfaces import TaskPlan


def graphbit_available() -> bool:
    """True when the ``graphbit`` distribution can be imported."""
    return importlib.util.find_spec("graphbit") is not None


class GraphBitWorkflowEngine:
    """Validate a plan with GraphBit, then run steps on the Python scheduler."""

    name = "graphbit"

    def __init__(self, module: Any | None = None) -> None:
        self._module = module

    def run(
        self,
        plan: TaskPlan,
        worker: Worker,
        *,
        concurrency: int,
        notes: dict[str, str],
        on_status: StatusCallback | None = None,
    ) -> None:
        module = self._load()
        _validate_graph(module, plan)
        # Imported lazily so this module and ``engine`` do not import each other
        # at load time.
        from swag_bot.core.engine import PythonWorkflowEngine

        PythonWorkflowEngine().run(
            plan,
            worker,
            concurrency=concurrency,
            notes=notes,
            on_status=on_status,
        )

    def _load(self) -> Any:
        if self._module is not None:
            return self._module
        if not graphbit_available():
            raise SwagError(
                "GraphBit is not installed. Install it with pip install 'swag-bot[graphbit]'."
            )
        return importlib.import_module("graphbit")


def _validate_graph(module: Any, plan: TaskPlan) -> None:
    init = getattr(module, "init", None)
    if callable(init):
        init()
    try:
        workflow = module.Workflow(plan.goal)
        node_ids: dict[str, Any] = {}
        for step in plan.steps:
            node = module.Node.agent(
                name=step.title,
                prompt=step.instruction or step.title,
                agent_id=step.id,
            )
            returned = workflow.add_node(node)
            node_ids[step.id] = step.id if returned is None else returned
        for step in plan.steps:
            for dep in step.depends_on:
                workflow.connect(node_ids[dep], node_ids[step.id])
        validate = getattr(workflow, "validate", None)
        if callable(validate):
            validate()
    except SwagError:
        raise
    except Exception as exc:
        raise SwagError(f"GraphBit rejected the plan graph: {exc}") from exc
