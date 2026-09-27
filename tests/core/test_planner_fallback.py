"""Unreadable plans are loud, and strict mode refuses the one-step fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from swag_bot.core.loop import LoopEvent, PlanDoVerifyLoop
from swag_bot.core.parsing import PlanParseError
from swag_bot.core.planner import Planner
from swag_bot.core.structured_output import PLAN_RESPONSE_FORMAT
from swag_bot.interfaces import AutonomyLevel, StepStatus
from tests.core.support import StaticPolicy, make_loop, plan_json, verdict
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore


def test_planner_sends_a_json_schema_and_records_fallback() -> None:
    llm = FakeLLMClient(["nope", "still nope"])
    planner = Planner(llm)
    plan = planner.create("ship the report", max_steps=4)
    assert planner.fell_back is True
    assert "not JSON" in planner.fallback_reason
    assert plan.steps[0].id == "step-1"
    assert plan.steps[0].title.startswith("ship the report")
    assert llm.formats[0] == PLAN_RESPONSE_FORMAT
    assert llm.formats[1] == PLAN_RESPONSE_FORMAT


def test_strict_planner_raises_instead_of_inventing_a_step() -> None:
    llm = FakeLLMClient(["nope", "still nope"])
    planner = Planner(llm, strict=True)
    with pytest.raises(PlanParseError, match="PLAN FALLBACK"):
        planner.create("ship the report", max_steps=4)
    assert planner.fell_back is True


def test_loop_emits_plan_fallback(tmp_path: Path) -> None:
    events: list[LoopEvent] = []
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        ["not json", "still not json", "I tried", verdict(False, "no"), "summary"],
        max_attempts=1,
    )
    loop.on_event = events.append
    plan = loop.run("do the thing")
    assert plan.steps[0].id == "step-1"
    assert plan.steps[0].status is StepStatus.FAILED
    kinds = [event.kind for event in events]
    assert "plan_fallback" in kinds
    fallback = next(event for event in events if event.kind == "plan_fallback")
    assert fallback.text
    assert kinds.index("plan_fallback") < kinds.index("plan")


def test_strict_loop_does_not_run_a_fallback_step(tmp_path: Path) -> None:
    llm = FakeLLMClient(["not json", "still not json", "should not run"])
    loop = PlanDoVerifyLoop(
        llm=llm,
        sandbox=FakeSandbox(tmp_path / "work"),
        memory=InMemoryMemoryStore(),
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        strict_plan=True,
        max_attempts=1,
    )
    with pytest.raises(PlanParseError, match="Strict planning"):
        loop.run("do the thing")
    assert loop.results == {}
    assert len(llm.messages) == 2


def test_readable_plan_does_not_fall_back(tmp_path: Path) -> None:
    events: list[LoopEvent] = []
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [plan_json([{"id": "only", "title": "Only", "instruction": "Do it"}])],
    )
    loop.on_event = events.append
    plan = loop.run("do it", dry_run=True)
    assert [step.id for step in plan.steps] == ["only"]
    assert llm.formats[0]["type"] == "json_schema"
    assert all(event.kind != "plan_fallback" for event in events)
