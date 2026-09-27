"""Optional per-run scaffold. ``None`` keeps the historical plan-do-verify loop.

The small-model harness builds these objects. The loop only reads them, so
this module does not import the harness package.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from swag_bot.interfaces import LLMClient, Step, StepResult, Tool


@dataclass(frozen=True)
class EarlyVerdict:
    """A check decided without another model call."""

    passed: bool
    reason: str
    replan: bool


ToolPicker = Callable[[Step, Sequence[Tool], int, set[str]], Sequence[Tool]]
Precheck = Callable[[Step, StepResult, Sequence[str]], EarlyVerdict | None]


@dataclass(frozen=True)
class RunScaffold:
    """Knobs the loop applies when a harness profile is active.

    ``None`` fields mean "use the loop default". ``max_steps`` is a cap: the
    caller's limit is lowered only when this value is smaller.
    """

    name: str
    max_steps: int | None = None
    max_tool_rounds: int | None = None
    planner_system: str | None = None
    executor_system: str | None = None
    verifier_system: str | None = None
    plan_schema: Mapping[str, Any] | None = None
    verdict_schema: Mapping[str, Any] | None = None
    strict_plan: bool = False
    pick_tools: ToolPicker | None = None
    precheck: Precheck | None = None
    guard_repeat_writes: bool = False
    retry_blank_turns: bool = False


@dataclass
class StepEscalation:
    """One stronger model for a step the active model failed.

    ``allow`` reserves budget and returns False when the step should stay on
    the active model. ``charge`` records the seconds the attempt actually took.
    """

    llm: LLMClient
    model: str
    allow: Callable[[], bool]
    charge: Callable[[float], None]
    label: str = ""
