"""The run summary keeps a single # Summary section."""

from __future__ import annotations

from swag_bot.core.summary import clean_model_summary, summarize
from swag_bot.interfaces import Step, StepResult, StepStatus, TaskPlan
from tests.fakes import FakeLLMClient


def _plan() -> tuple[TaskPlan, dict[str, StepResult]]:
    plan = TaskPlan(
        goal="write a note",
        steps=[Step(id="write", title="Write", status=StepStatus.DONE)],
    )
    results = {
        "write": StepResult(
            step_id="write",
            status=StepStatus.DONE,
            observation="wrote note.txt",
            verified=True,
        )
    }
    return plan, results


def test_fenced_summary_heading_is_not_repeated() -> None:
    plan, results = _plan()
    fenced = "```markdown\n# Summary\n\nDone.\n\n## Steps\n\n- write done\n\n## Result\n\nok\n```"
    text = summarize(FakeLLMClient([fenced]), plan, results, remembered=["remembered: wrote it"])
    assert text.count("# Summary") == 1
    assert "```" not in text
    assert "remembered: wrote it" in text
    assert text.index("## Memory") > text.index("# Summary")


def test_short_narrative_keeps_one_record() -> None:
    plan, results = _plan()
    text = summarize(FakeLLMClient(["# Summary\n\nThe note was written."]), plan, results)
    assert text.count("# Summary") == 1
    assert "The note was written." in text
    assert "wrote note.txt" in text


def test_clean_model_summary_unwraps_a_fence() -> None:
    assert clean_model_summary("```\n# Summary\n\nDone.\n```") == "Done."
    assert clean_model_summary("   ") == ""
