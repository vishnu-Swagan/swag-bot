"""Rich approval prompt."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from swag_bot.interfaces import ActionKind, ActionRequest, RiskLevel
from swag_bot.safety.prompter import RichApprovalPrompter


def test_prompter_shows_the_action_and_returns_the_answer() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, no_color=True, width=80)
    answers = iter([True, False])

    def confirm(prompt: str, *, default: bool = False) -> bool:
        assert "Allow" in prompt
        assert default is False
        return next(answers)

    prompter = RichApprovalPrompter(console=console, confirm=confirm)
    action = ActionRequest(
        kind=ActionKind.RUN_COMMAND.value,
        summary="run the tests",
        risk=RiskLevel.EXECUTE,
        target="pytest",
        arguments={"plugin": "demo"},
    )
    assert prompter.prompt(action) is True
    assert prompter.prompt(action) is False
    text = buffer.getvalue()
    assert "run the tests" in text
    assert "execute" in text
    assert "pytest" in text
    assert "demo" in text
