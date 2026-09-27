"""Helpers for core tests. Not collected by pytest."""

from __future__ import annotations

import json
from pathlib import Path

from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.interfaces import (
    ActionRequest,
    AutonomyLevel,
    RiskLevel,
    default_requires_approval,
)
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore


class StaticPolicy:
    """Permission policy that follows ``default_requires_approval``."""

    def __init__(self, autonomy: AutonomyLevel) -> None:
        self._autonomy = autonomy

    @property
    def autonomy(self) -> AutonomyLevel:
        return self._autonomy

    def classify(self, action: ActionRequest) -> RiskLevel:
        return action.risk

    def requires_approval(self, action: ActionRequest) -> bool:
        return default_requires_approval(self.autonomy, self.classify(action))


class DenyPrompter:
    """Records prompts and denies every one."""

    def __init__(self) -> None:
        self.prompts: list[ActionRequest] = []

    def prompt(self, action: ActionRequest) -> bool:
        self.prompts.append(action)
        return False


def plan_json(steps: list[dict[str, object]]) -> str:
    return json.dumps({"steps": steps})


def verdict(passed: bool, reason: str = "ok", *, replan: bool = False) -> str:
    return json.dumps({"passed": passed, "reason": reason, "replan": replan})


def make_loop(
    tmp_path: Path,
    responses: list[object],
    *,
    autonomy: AutonomyLevel = AutonomyLevel.ASK_RISKY,
    prompter: object | None = None,
    max_steps: int = 8,
    max_attempts: int = 2,
    concurrency: int = 1,
    engine: str = "python",
    graphbit_module: object | None = None,
    tools: object | None = None,
) -> tuple[PlanDoVerifyLoop, FakeLLMClient, FakeSandbox, InMemoryMemoryStore]:
    llm = FakeLLMClient(responses)  # type: ignore[arg-type]
    sandbox = FakeSandbox(tmp_path / "work")
    memory = InMemoryMemoryStore()
    policy = StaticPolicy(autonomy)
    loop = PlanDoVerifyLoop(
        llm=llm,
        sandbox=sandbox,
        memory=memory,
        policy=policy,
        prompter=prompter if prompter is not None else AutoApprovePrompter(),  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
        max_steps=max_steps,
        max_attempts=max_attempts,
        concurrency=concurrency,
        engine=engine,
        graphbit_module=graphbit_module,
    )
    return loop, llm, sandbox, memory
