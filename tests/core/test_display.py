"""Progress lines print once, and prompts suspend the live table."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from swag_bot.core.display import PromptSuspender, RunProgress, TaskListView
from swag_bot.core.loop import LoopEvent
from swag_bot.interfaces import ActionRequest, RiskLevel, Step, StepStatus, TaskPlan


def _console(buf: StringIO) -> Console:
    return Console(file=buf, force_terminal=False, no_color=True, highlight=False, width=80)


def test_step_id_prefix_is_not_eaten_as_markup() -> None:
    buf = StringIO()
    eaten = StringIO()
    plain = Console(file=eaten, force_terminal=False, no_color=True, highlight=False, width=80)
    plain.print("[step-1] wrote the file")
    view = TaskListView(_console(buf))
    view.note("[step-1] wrote the file")
    assert "[step-1]" not in eaten.getvalue()
    assert "[step-1] wrote the file" in buf.getvalue()


def test_status_and_output_are_recorded_once() -> None:
    buf = StringIO()
    view = TaskListView(_console(buf))
    progress = RunProgress(view)
    plan = TaskPlan(
        goal="write hello",
        steps=[Step(id="write", title="Write hello", status=StepStatus.DONE)],
    )
    progress(LoopEvent(kind="status", plan=plan, step_id="write", status="done"))
    progress(LoopEvent(kind="output", plan=plan, step_id="write", text="wrote hello.txt"))
    progress(LoopEvent(kind="status", plan=plan, step_id="write", status="done"))
    text = buf.getvalue()
    assert text.count("[done] write Write hello") == 1
    assert text.count("[write] wrote hello.txt") == 1


def test_fallback_line_is_loud() -> None:
    buf = StringIO()
    view = TaskListView(_console(buf))
    plan = TaskPlan(goal="do it", steps=[Step(id="step-1", title="do it")])
    RunProgress(view)(LoopEvent(kind="plan_fallback", plan=plan, text="not JSON"))
    text = buf.getvalue()
    assert "PLAN FALLBACK" in text
    assert "--strict-plan" in text
    assert "not JSON" in text


def test_prompt_runs_while_the_live_view_is_suspended() -> None:
    buf = StringIO()
    view = TaskListView(_console(buf))
    seen: list[int] = []

    class _Inner:
        def prompt(self, action: ActionRequest) -> bool:
            del action
            seen.append(view._depth)
            view.note("panel stayed")
            return True

    action = ActionRequest(kind="write_file", summary="write hello.txt", risk=RiskLevel.WRITE)
    with view:
        assert PromptSuspender(_Inner(), view).prompt(action) is True
    assert seen == [1]
    assert "panel stayed" in buf.getvalue()
    assert view._depth == 0
