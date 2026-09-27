"""Final markdown summary of a plan."""

from __future__ import annotations

from swag_bot.core.prompts import SUMMARIZER_SYSTEM
from swag_bot.interfaces import LLMClient, Message, StepResult, StepStatus, TaskPlan


def summarize(
    llm: LLMClient,
    plan: TaskPlan,
    results: dict[str, StepResult],
    *,
    model: str | None = None,
    dry_run: bool = False,
) -> str:
    """Build ``summary.md``. A dry run does not call the model."""
    structured = render_record(plan, results, dry_run=dry_run)
    if dry_run:
        return structured
    response = llm.chat(
        [Message.system(SUMMARIZER_SYSTEM), Message.user(structured)],
        model=model,
    )
    prose = (response.message.content or "").strip()
    if not prose:
        return structured
    return f"{prose}\n\n{structured}"


def render_record(
    plan: TaskPlan,
    results: dict[str, StepResult],
    *,
    dry_run: bool = False,
) -> str:
    """Deterministic markdown the model summary is appended to."""
    counts = {status.value: 0 for status in StepStatus}
    for step in plan.steps:
        counts[step.status.value] = counts.get(step.status.value, 0) + 1
    lines = ["# Summary", "", f"Goal: {plan.goal}", ""]
    if dry_run:
        lines.extend(["Dry run. The plan was not executed.", ""])
    lines.append("## Steps")
    lines.append("")
    if not plan.steps:
        lines.append("(no steps)")
    for step in plan.steps:
        lines.append(f"- `{step.id}` **{step.status.value}**: {step.title}")
        result = results.get(step.id)
        if result is not None and result.observation:
            lines.append(f"  - {_clip(result.observation)}")
        if result is not None and result.error:
            lines.append(f"  - error: {_clip(result.error)}")
    lines.append("")
    lines.append("## Result")
    lines.append("")
    lines.append(
        "{done} done, {failed} failed, {skipped} skipped, {pending} pending.".format(
            done=counts.get("done", 0),
            failed=counts.get("failed", 0),
            skipped=counts.get("skipped", 0),
            pending=counts.get("pending", 0),
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def _clip(text: str, limit: int = 2000) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."
