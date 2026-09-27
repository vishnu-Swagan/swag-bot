"""Final markdown summary of a plan."""

from __future__ import annotations

import re
from collections.abc import Sequence

from swag_bot.core.prompts import SUMMARIZER_SYSTEM
from swag_bot.interfaces import LLMClient, Message, StepResult, StepStatus, TaskPlan

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```$", re.DOTALL)
_SUMMARY_HEADING = re.compile(r"^#\s*Summary\s*\n+", re.IGNORECASE)


def summarize(
    llm: LLMClient,
    plan: TaskPlan,
    results: dict[str, StepResult],
    *,
    model: str | None = None,
    dry_run: bool = False,
    remembered: Sequence[str] = (),
) -> str:
    """Build ``summary.md``. A dry run does not call the model.

    The model may add a short narrative. The step record is the only
    ``# Summary`` section. A fenced copy of that record is dropped.
    """
    structured = render_record(plan, results, dry_run=dry_run, remembered=remembered)
    if dry_run:
        return structured
    response = llm.chat(
        [Message.system(SUMMARIZER_SYSTEM), Message.user(structured)],
        model=model,
    )
    prose = clean_model_summary(response.message.content or "")
    if not prose:
        return structured
    return f"{prose}\n\n{structured}"


def clean_model_summary(text: str) -> str:
    """Drop a wrapping code fence, a leading ``# Summary``, and an echoed step record."""
    raw = text.strip()
    if not raw:
        return ""
    fenced = _FENCE.match(raw)
    if fenced:
        raw = fenced.group(1).strip()
    raw = _SUMMARY_HEADING.sub("", raw, count=1).strip()
    if _looks_like_record(raw):
        return ""
    return raw


def _looks_like_record(text: str) -> bool:
    folded = text.casefold()
    return "## steps" in folded and ("## result" in folded or "goal:" in folded)


def render_record(
    plan: TaskPlan,
    results: dict[str, StepResult],
    *,
    dry_run: bool = False,
    remembered: Sequence[str] = (),
) -> str:
    """Deterministic markdown. This is the only ``# Summary`` section."""
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
    if remembered:
        lines.extend(["", "## Memory", ""])
        for line in remembered:
            lines.append(f"- {line}")
    return "\n".join(lines).rstrip() + "\n"


def _clip(text: str, limit: int = 2000) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."
