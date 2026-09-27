"""Turn a goal into a ``TaskPlan`` by asking the injected ``LLMClient``."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from swag_bot.core.parsing import PlanParseError, extract_json
from swag_bot.core.prompts import PLANNER_SYSTEM
from swag_bot.core.structured import chat_structured
from swag_bot.interfaces import LLMClient, Message, Step, TaskPlan

_WS = re.compile(r"\s+")
_SAMPLE_IDS = frozenset(
    {
        "short-id",
        "step-id",
        "example",
        "example-id",
        "your-id",
        "sample",
        "sample-id",
        "todo",
        "id",
    }
)
_SAMPLE_TITLES = frozenset({"what this step does"})
_SAMPLE_INSTRUCTION = "how to do it with the available tools"


class Planner:
    """Ask the model for a plan, then for replacement steps after a failed check."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        model: str | None = None,
        tool_names: Sequence[str] = (),
        context: str = "",
        system: str | None = None,
        response_schema: Mapping[str, Any] | None = None,
        strict: bool = False,
    ) -> None:
        self.llm = llm
        self.model = model
        self.tool_names = list(tool_names)
        self.context = context
        self.system = PLANNER_SYSTEM if system is None else system
        self.response_schema = response_schema
        self.strict = strict

    def create(self, goal: str, *, max_steps: int) -> TaskPlan:
        """Return a plan for ``goal``. Fall back to one step if the model is unreadable."""
        feedback: str | None = None
        for _ in range(2):
            try:
                payload = self._ask(
                    _create_prompt(goal, self.tool_names, max_steps, feedback, self.context)
                )
                steps = steps_from_payload(
                    payload,
                    limit=max_steps,
                    existing_ids=set(),
                    strict=self.strict,
                )
            except PlanParseError as exc:
                feedback = str(exc)
                continue
            if not steps:
                feedback = "The plan had no steps."
                continue
            return TaskPlan(goal=goal, steps=steps)
        return TaskPlan(goal=goal, steps=[fallback_step(goal)])

    def revise(
        self,
        plan: TaskPlan,
        failures: Sequence[tuple[Step, str]],
        *,
        max_new: int,
    ) -> list[Step]:
        """Ask for up to ``max_new`` steps that replace a failed approach.

        Returns an empty list when there is no room or the model cannot be parsed.
        """
        if max_new <= 0 or not failures:
            return []
        feedback: str | None = None
        existing = {step.id for step in plan.steps}
        for _ in range(2):
            prompt = _revise_prompt(plan, failures, max_new, feedback, self.context)
            try:
                payload = self._ask(prompt)
                return steps_from_payload(
                    payload,
                    limit=max_new,
                    existing_ids=set(existing),
                    strict=self.strict,
                )
            except PlanParseError as exc:
                feedback = str(exc)
        return []

    def _ask(self, user: str) -> Any:
        response = chat_structured(
            self.llm,
            [Message.system(self.system), Message.user(user)],
            model=self.model,
            response_schema=self.response_schema,
        )
        try:
            return extract_json(response.message.content or "")
        except PlanParseError as exc:
            raise PlanParseError(str(exc)) from exc


def fallback_step(goal: str) -> Step:
    """One step used when the model never returns a readable plan."""
    title = goal.strip().splitlines()[0][:80] if goal.strip() else "complete the goal"
    return Step(
        id="step-1",
        title=title or "complete the goal",
        instruction=f"{goal.strip()}\n\nSuccess criteria: The goal is complete.",
    )


def steps_from_payload(
    payload: Any,
    *,
    limit: int,
    existing_ids: set[str],
    strict: bool = False,
) -> list[Step]:
    """Validate a model payload into steps.

    ``existing_ids`` are ids already on the plan (a replan). New ids are kept
    unique against that set. Unknown dependency ids raise ``PlanParseError``.

    ``strict`` rejects a plan that copied the sample id or sample wording, and
    rejects a plan that is longer than ``limit`` instead of silently dropping
    the tail. Small models were copying ``short-id`` and splitting a one-file
    task into more steps than the limit.
    """
    raw_steps = _raw_steps(payload)
    if limit < 1:
        raise PlanParseError("the step limit must be at least 1")
    if strict and len(raw_steps) > limit:
        raise PlanParseError(
            f"the plan has {len(raw_steps)} steps and the limit is {limit}. "
            "Use fewer steps. A goal that writes one file and runs it is one step."
        )
    selected = raw_steps[:limit]
    used = set(existing_ids)
    built: list[tuple[Step, list[str]]] = []
    for index, item in enumerate(selected, start=1):
        if not isinstance(item, dict):
            raise PlanParseError(f"step {index} must be an object")
        requested = _text(item.get("id")) or f"step-{len(used) + 1}"
        title = _text(item.get("title")) or requested
        criteria = _text(item.get("success_criteria") or item.get("successCriteria"))
        instruction = _fold_criteria(_text(item.get("instruction")), criteria)
        if strict and _is_sample(requested, title, instruction):
            raise PlanParseError(
                "the plan copied a sample id or sample wording. "
                "Choose ids and wording for this goal."
            )
        step_id = _unique_id(requested, used)
        title = title or step_id
        depends = _depends(item)
        built.append((Step(id=step_id, title=title, instruction=instruction), depends))
    known = set(existing_ids)
    known.update(step.id for step, _depends_on in built)
    steps: list[Step] = []
    for step, depends in built:
        missing = [dep for dep in depends if dep not in known]
        if missing:
            raise PlanParseError(f"step {step.id} depends on unknown steps: {missing}")
        # A step cannot depend on itself.
        step.depends_on = [dep for dep in depends if dep != step.id]
        steps.append(step)
    return steps


def _raw_steps(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        steps = payload.get("steps", payload.get("plan"))
        if isinstance(steps, list):
            return steps
        raise PlanParseError("the plan JSON needs a steps array")
    if isinstance(payload, list):
        return payload
    raise PlanParseError("the plan JSON needs a steps array")


def _depends(item: dict[str, Any]) -> list[str]:
    raw = item.get("depends_on", item.get("dependsOn", []))
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if not isinstance(raw, list):
        raise PlanParseError("depends_on must be a list of step ids")
    deps: list[str] = []
    for entry in raw:
        text = _text(entry)
        if text and text not in deps:
            deps.append(text)
    return deps


def _fold_criteria(instruction: str, criteria: str) -> str:
    if not criteria or "success criteria:" in instruction.casefold():
        return instruction
    if instruction:
        return f"{instruction}\n\nSuccess criteria: {criteria}"
    return f"Success criteria: {criteria}"


def _unique_id(requested: str, used: set[str]) -> str:
    base = _WS.sub("-", requested.strip()) or "step"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_sample(step_id: str, title: str, instruction: str) -> bool:
    token = _WS.sub("-", step_id.strip()).casefold()
    if token in _SAMPLE_IDS:
        return True
    if title.strip().casefold() in _SAMPLE_TITLES:
        return True
    return _SAMPLE_INSTRUCTION in instruction.casefold()


def _create_prompt(
    goal: str,
    tool_names: Sequence[str],
    max_steps: int,
    feedback: str | None,
    context: str = "",
) -> str:
    tools = ", ".join(tool_names) if tool_names else "(none)"
    lines = [
        f"Goal:\n{goal.strip()}",
        f"Step limit: {max_steps}",
        f"Tools: {tools}",
    ]
    if context.strip():
        lines.append(context.strip())
    if feedback:
        lines.append(f"Your previous plan could not be used: {feedback}")
        lines.append("Return a corrected JSON plan.")
    return "\n\n".join(lines)


def _revise_prompt(
    plan: TaskPlan,
    failures: Sequence[tuple[Step, str]],
    max_new: int,
    feedback: str | None,
    context: str = "",
) -> str:
    done = [step for step in plan.steps if step.status.value == "done"]
    lines = [
        f"Goal:\n{plan.goal}",
        f"Add at most {max_new} new steps. Do not repeat ids that already exist.",
        "Existing step ids: " + ", ".join(step.id for step in plan.steps),
    ]
    if done:
        lines.append("Finished steps:")
        lines.extend(f"- {step.id}: {step.title}" for step in done)
    if context.strip():
        lines.append(context.strip())
    lines.append("These steps failed their check and need a different approach:")
    for step, reason in failures:
        lines.append(f"- {step.id} ({step.title}): {reason}")
    if feedback:
        lines.append(f"Your previous replacement could not be used: {feedback}")
    lines.append("Return JSON with a steps array of the new steps only.")
    return "\n".join(lines)
