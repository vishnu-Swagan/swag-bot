"""Scheduler: dependencies, concurrency, cycles, and the GraphBit adapter."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from swag_bot.core.engine import PythonWorkflowEngine, build_engine
from swag_bot.core.graphbit import GraphBitWorkflowEngine, graphbit_available
from swag_bot.errors import SwagError
from swag_bot.interfaces import Step, StepStatus, TaskPlan


def _plan(*steps: Step) -> TaskPlan:
    return TaskPlan(goal="ship it", steps=list(steps))


def _finish(step: Step) -> None:
    step.status = StepStatus.DONE


def test_dependency_order() -> None:
    plan = _plan(
        Step(id="b", title="Second", depends_on=["a"]),
        Step(id="a", title="First"),
    )
    order: list[str] = []

    def worker(step: Step) -> None:
        order.append(step.id)
        _finish(step)

    PythonWorkflowEngine().run(plan, worker, concurrency=2, notes={})
    assert order == ["a", "b"]
    assert [step.status for step in plan.steps] == [StepStatus.DONE, StepStatus.DONE]


def test_failed_dependency_skips_later_steps_regardless_of_order() -> None:
    plan = _plan(
        Step(id="c", title="Third", depends_on=["b"]),
        Step(id="b", title="Second", depends_on=["a"]),
        Step(id="a", title="First"),
    )
    notes: dict[str, str] = {}

    def worker(step: Step) -> None:
        step.status = StepStatus.FAILED if step.id == "a" else StepStatus.DONE

    PythonWorkflowEngine().run(plan, worker, concurrency=2, notes=notes)
    by_id = {step.id: step.status for step in plan.steps}
    assert by_id == {
        "a": StepStatus.FAILED,
        "b": StepStatus.SKIPPED,
        "c": StepStatus.SKIPPED,
    }
    assert "dependency" in notes["c"].lower()


def test_cycle_fails_without_running_workers() -> None:
    plan = _plan(
        Step(id="a", title="A", depends_on=["b"]),
        Step(id="b", title="B", depends_on=["a"]),
    )
    notes: dict[str, str] = {}
    called: list[str] = []

    def worker(step: Step) -> None:
        called.append(step.id)
        _finish(step)

    PythonWorkflowEngine().run(plan, worker, concurrency=2, notes=notes)
    assert called == []
    assert all(step.status == StepStatus.FAILED for step in plan.steps)
    assert notes["a"] == "Dependency cycle."


def test_independent_steps_overlap_and_concurrency_is_capped() -> None:
    plan = _plan(
        Step(id="a", title="A"),
        Step(id="b", title="B"),
        Step(id="c", title="C"),
    )
    state = {"current": 0, "max": 0}
    lock = threading.Lock()

    def worker(step: Step) -> None:
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.15)
        with lock:
            state["current"] -= 1
        _finish(step)

    PythonWorkflowEngine().run(plan, worker, concurrency=2, notes={})
    assert state["max"] == 2
    assert all(step.status == StepStatus.DONE for step in plan.steps)

    serial = _plan(Step(id="a", title="A"), Step(id="b", title="B"))
    serial_state = {"current": 0, "max": 0}

    def serial_worker(step: Step) -> None:
        with lock:
            serial_state["current"] += 1
            serial_state["max"] = max(serial_state["max"], serial_state["current"])
        time.sleep(0.05)
        with lock:
            serial_state["current"] -= 1
        _finish(step)

    PythonWorkflowEngine().run(serial, serial_worker, concurrency=1, notes={})
    assert serial_state["max"] == 1


def test_worker_exception_fails_the_step() -> None:
    plan = _plan(Step(id="a", title="A"), Step(id="b", title="B", depends_on=["a"]))
    notes: dict[str, str] = {}

    def worker(step: Step) -> None:
        raise RuntimeError("boom")

    PythonWorkflowEngine().run(plan, worker, concurrency=1, notes=notes)
    assert plan.steps[0].status == StepStatus.FAILED
    assert "boom" in notes["a"]
    assert plan.steps[1].status == StepStatus.SKIPPED


def test_core_modules_do_not_import_other_packages() -> None:
    """The loop codes against interfaces. Only ``cli.py`` calls factories."""
    forbidden = (
        "swag_bot.models",
        "swag_bot.memory",
        "swag_bot.safety",
        "swag_bot.mcp",
        "swag_bot.plugins",
    )
    root = Path("src/swag_bot/core")
    for path in root.glob("*.py"):
        if path.name == "cli.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in text, f"{path.name} imports {name}"


def test_python_engine_is_the_default_and_graphbit_is_optional() -> None:
    engine, note = build_engine("python")
    assert engine.name == "python"
    assert note == ""
    assert graphbit_available() is False
    fallback, fallback_note = build_engine("graphbit")
    assert isinstance(fallback, PythonWorkflowEngine)
    assert "not installed" in fallback_note
    auto, auto_note = build_engine("auto")
    assert isinstance(auto, PythonWorkflowEngine)
    assert auto_note == ""
    with pytest.raises(ValueError, match="unknown workflow engine"):
        build_engine("nope")


class _FakeGraphBit:
    def __init__(self) -> None:
        self.inited = False
        self.workflows: list[_Workflow] = []

    def init(self) -> None:
        self.inited = True

    def Workflow(self, name: str) -> _Workflow:
        workflow = _Workflow(name)
        self.workflows.append(workflow)
        return workflow

    class Node:
        @staticmethod
        def agent(**kwargs: object) -> dict[str, object]:
            return dict(kwargs)


class _Workflow:
    def __init__(self, name: str) -> None:
        self.name = name
        self.nodes: list[dict[str, object]] = []
        self.edges: list[tuple[object, object]] = []
        self.validated = False

    def add_node(self, node: dict[str, object]) -> str:
        self.nodes.append(node)
        agent_id = node.get("agent_id")
        return str(agent_id)

    def connect(self, source: object, target: object) -> None:
        self.edges.append((source, target))

    def validate(self) -> None:
        self.validated = True


class _InvalidGraphBit(_FakeGraphBit):
    def Workflow(self, name: str) -> _Workflow:
        workflow = _InvalidWorkflow(name)
        self.workflows.append(workflow)
        return workflow


class _InvalidWorkflow(_Workflow):
    def validate(self) -> None:
        raise RuntimeError("cycle")


def test_graphbit_validates_edges_then_runs_workers() -> None:
    module = _FakeGraphBit()
    plan = _plan(
        Step(id="a", title="First", instruction="do a"),
        Step(id="b", title="Second", depends_on=["a"]),
    )
    ran: list[str] = []

    def worker(step: Step) -> None:
        ran.append(step.id)
        _finish(step)

    engine = GraphBitWorkflowEngine(module=module)
    engine.run(plan, worker, concurrency=1, notes={})
    assert engine.name == "graphbit"
    assert module.inited is True
    workflow = module.workflows[0]
    assert workflow.validated is True
    assert workflow.edges == [("a", "b")]
    assert ran == ["a", "b"]
    assert workflow.nodes[0]["prompt"] == "do a"


def test_graphbit_rejection_does_not_run_workers() -> None:
    plan = _plan(Step(id="a", title="A"))
    called: list[str] = []

    def worker(step: Step) -> None:
        called.append(step.id)
        _finish(step)

    with pytest.raises(SwagError, match="rejected"):
        GraphBitWorkflowEngine(module=_InvalidGraphBit()).run(plan, worker, concurrency=1, notes={})
    assert called == []
