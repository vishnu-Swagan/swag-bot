"""Final markdown summary of a plan.

The summary is built from the step record and the evidence ledger. Model prose
is kept only when it does not claim a result the ledger does not support.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from swag_bot.core.prompts import SUMMARIZER_SYSTEM
from swag_bot.interfaces import (
    CheckResult,
    Evidence,
    LLMClient,
    Message,
    StepResult,
    StepStatus,
    TaskPlan,
)

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```$", re.DOTALL)
_SUMMARY_HEADING = re.compile(r"^#\s*Summary\s*\n+", re.IGNORECASE)
_FENCE_LINE = re.compile(r"^```.*$", re.MULTILINE)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]*)`")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_RUN_CLAIM = re.compile(r"\b(was run|were run|\bran\b|executed|was executed)\b", re.IGNORECASE)
_PRINTED_CLAIM = re.compile(r"\bprinted\b", re.IGNORECASE)
_LAST_LINE_CLAIM = re.compile(r"\blast\s+line\b", re.IGNORECASE)
_GOAL_MET_CLAIM = re.compile(r"\bgoal met\b", re.IGNORECASE)
_LAST_LINE_VALUE = re.compile(
    r"\blast\s+line\b.{0,40}?\b(?:is|was)\s+[\"']?([A-Za-z0-9_+-]+)",
    re.IGNORECASE,
)
_ECHO_SPLIT = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:goal|steps|result)\s*:|"
    r"\s+-\s+\*{0,2}(?:met|unverified|not met)\*{0,2}\s*:|"
    r"\s+goal\s*:|\s+steps\s*:|\s+result\s*:",
    re.IGNORECASE,
)
_GOAL_HEAD = re.compile(r"^(?:goal met|goal not met)\.?\s*", re.IGNORECASE)
_ONLY_HEADLINE = re.compile(r"^(?:goal met|goal not met)\.?$", re.IGNORECASE)
_RECORD_LINE = re.compile(
    r"^(?:goal|steps|result)\b|^\d+ done,|^[-*]\s+(?:met|unverified|not met)\b",
    re.IGNORECASE,
)


def summarize(
    llm: LLMClient,
    plan: TaskPlan,
    results: dict[str, StepResult],
    *,
    model: str | None = None,
    dry_run: bool = False,
    remembered: Sequence[str] = (),
    goal_results: Sequence[CheckResult] = (),
    evidence: Sequence[Evidence] = (),
) -> str:
    """Build ``summary.md``. A dry run does not call the model.

    The step record is the only ``# Summary`` section. Model prose that claims
    a run, a printed line, or a met goal without ledger evidence is marked
    unverified or dropped. A fenced copy of the step record is dropped.
    """
    prose = ""
    if not dry_run:
        record_for_model = render_record(
            plan, results, dry_run=False, remembered=remembered, goal_results=goal_results
        )
        response = llm.chat(
            [Message.system(SUMMARIZER_SYSTEM), Message.user(record_for_model)],
            model=model,
        )
        prose = filter_unbacked_claims(
            clean_model_summary(response.message.content or ""),
            evidence,
            goal_results,
        )
    return render_record(
        plan,
        results,
        dry_run=dry_run,
        remembered=remembered,
        goal_results=goal_results,
        prose=prose,
    )


def clean_model_summary(text: str) -> str:
    """Keep at most two plain sentences. Drop an echoed check list or step record."""
    raw = text.strip()
    if not raw:
        return ""
    fenced = _FENCE.match(raw)
    if fenced:
        raw = fenced.group(1).strip()
    raw = _SUMMARY_HEADING.sub("", raw, count=1).strip()
    raw = plain_terminal(raw)
    raw = _ECHO_SPLIT.split(raw, maxsplit=1)[0].strip()
    kept_lines: list[str] = []
    for line in raw.splitlines():
        folded = line.strip()
        if not folded:
            continue
        if _RECORD_LINE.match(folded):
            break
        kept_lines.append(folded)
    raw = " ".join(kept_lines).strip()
    raw = _GOAL_HEAD.sub("", raw).strip()
    if _looks_like_record(raw):
        return ""
    sentences = [item.strip() for item in _SENTENCE.split(raw) if item.strip()]
    short: list[str] = []
    for sentence in sentences:
        if _ONLY_HEADLINE.match(sentence):
            continue
        short.append(sentence)
        if len(short) == 2:
            break
    return " ".join(short).strip()


def plain_terminal(text: str) -> str:
    """Drop fences, bold markers, and backticks. Leave bracketed step ids alone."""
    cleaned = _FENCE_LINE.sub("", text)
    cleaned = _BOLD.sub(r"\1", cleaned)
    cleaned = _CODE.sub(r"\1", cleaned)
    return cleaned


def aborted_summary(goal: str, error: str, plan: TaskPlan | None = None) -> str:
    """Honest summary when a run stops before the model can finish one."""
    lines = [
        "# Summary",
        "",
        "Goal not met.",
        "",
        "The run stopped before it finished.",
        "",
        error.strip() or "The model request failed.",
        "",
        f"Goal: {goal}",
        "",
    ]
    if plan is not None and plan.steps:
        lines.append("## Steps")
        lines.append("")
        for step in plan.steps:
            lines.append(f"- {step.id} {step.status.value}: {step.title}")
        lines.append("")
    lines.extend(["## Result", "", "The run did not finish. This is not a success."])
    return "\n".join(lines).rstrip() + "\n"


def _looks_like_record(text: str) -> bool:
    folded = text.casefold()
    return "## steps" in folded and ("## result" in folded or "goal:" in folded)


def render_for_terminal(summary: str) -> str:
    """Plain text for the terminal. No raw bold markers, fences, or heading marks."""
    text = plain_terminal(summary)
    text = _HEADING.sub("", text)
    cleaned: list[str] = []
    blank = 0
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped.strip():
            blank += 1
            if blank <= 1:
                cleaned.append("")
            continue
        blank = 0
        cleaned.append(stripped)
    return "\n".join(cleaned).strip()


def filter_unbacked_claims(
    prose: str,
    evidence: Sequence[Evidence],
    goal_results: Sequence[CheckResult] = (),
) -> str:
    """Mark or drop sentences the evidence ledger does not support."""
    raw = prose.strip()
    if not raw:
        return ""
    unmet = bool(goal_results) and any(
        not item.passed or not item.evidence_ids for item in goal_results
    )
    ran = _command_succeeded(evidence)
    kept: list[str] = []
    for sentence in _SENTENCE.split(raw):
        text = sentence.strip()
        if not text:
            continue
        if unmet and _GOAL_MET_CLAIM.search(text):
            continue
        if _sentence_unbacked(text, evidence, goal_results, ran=ran):
            kept.append(f"(unverified) {text}")
            continue
        kept.append(text)
    return " ".join(kept).strip()


def render_record(
    plan: TaskPlan,
    results: dict[str, StepResult],
    *,
    dry_run: bool = False,
    remembered: Sequence[str] = (),
    goal_results: Sequence[CheckResult] = (),
    prose: str = "",
) -> str:
    """Deterministic markdown. This is the only ``# Summary`` section."""
    counts = {status.value: 0 for status in StepStatus}
    for step in plan.steps:
        counts[step.status.value] = counts.get(step.status.value, 0) + 1
    lines = ["# Summary", ""]
    headline = _goal_headline(plan, goal_results)
    if headline:
        lines.extend([headline, ""])
    if goal_results:
        for item in goal_results:
            if item.passed and item.evidence_ids:
                state = "met"
            elif item.evidence_ids:
                state = "not met"
            else:
                state = "unverified"
            cited = ", ".join(item.evidence_ids) if item.evidence_ids else "none"
            lines.append(f"- {state}: {item.detail} (evidence: {cited})")
        lines.append("")
    if prose.strip():
        lines.extend([prose.strip(), ""])
    lines.extend([f"Goal: {plan.goal}", ""])
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
        if result is not None and result.evidence_ids:
            lines.append(f"  - evidence: {', '.join(result.evidence_ids)}")
    lines.append("")
    lines.append("## Result")
    lines.append("")
    lines.append(
        "{done} done, {failed} failed, {unverified} unverified, "
        "{skipped} skipped, {pending} pending.".format(
            done=counts.get("done", 0),
            failed=counts.get("failed", 0),
            unverified=counts.get("unverified", 0),
            skipped=counts.get("skipped", 0),
            pending=counts.get("pending", 0),
        )
    )
    if remembered:
        lines.extend(["", "## Memory", ""])
        for line in remembered:
            lines.append(f"- {line}")
    return "\n".join(lines).rstrip() + "\n"


def _goal_headline(plan: TaskPlan, goal_results: Sequence[CheckResult]) -> str:
    if goal_results:
        unmet = [item for item in goal_results if not item.passed or not item.evidence_ids]
        if unmet:
            return "Goal not met."
        return "Goal met."
    failed = any(step.status in {StepStatus.FAILED, StepStatus.UNVERIFIED} for step in plan.steps)
    if failed:
        return "Goal not met."
    return ""


def _sentence_unbacked(
    sentence: str,
    evidence: Sequence[Evidence],
    goal_results: Sequence[CheckResult],
    *,
    ran: bool,
) -> bool:
    if _RUN_CLAIM.search(sentence) and not ran:
        return True
    if _PRINTED_CLAIM.search(sentence) and not ran:
        return True
    if _LAST_LINE_CLAIM.search(sentence) and not _last_line_backed(
        sentence, evidence, goal_results
    ):
        return True
    return False


def _command_succeeded(evidence: Sequence[Evidence]) -> bool:
    for item in evidence:
        ran_shell = item.tool == "run_shell" or bool(item.stdout)
        if item.exit_code == 0 and item.ok is not False and ran_shell:
            return True
    return False


def _last_line_backed(
    sentence: str,
    evidence: Sequence[Evidence],
    goal_results: Sequence[CheckResult],
) -> bool:
    """True when the sentence agrees with captured output.

    A true report of the last line stays, even when a goal check wanted a
    different line. A claim is unverified only when it contradicts the
    output or no output was captured.
    """
    observed = _observed_last_lines(evidence)
    claimed = _LAST_LINE_VALUE.search(sentence)
    if claimed is not None:
        return claimed.group(1) in observed
    if observed:
        return True
    for item in goal_results:
        ident = f"{item.check_id} {item.detail}".casefold().replace("-", " ")
        if "last line" in ident and item.passed and item.evidence_ids:
            return True
    return False


def _observed_last_lines(evidence: Sequence[Evidence]) -> set[str]:
    found: set[str] = set()
    for item in evidence:
        lines = [line.strip() for line in item.stdout.splitlines() if line.strip()]
        if lines:
            found.add(lines[-1])
    return found


def _clip(text: str, limit: int = 2000) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."
