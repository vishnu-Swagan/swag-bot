"""Loop and CLI: uncertain steps ask, and the jury blocks a bad irreversible action."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.config import EscalationSettings
from swag_bot.core.escalation import EscalationController
from swag_bot.core.escalation_prompt import ClarificationRequest
from swag_bot.core.jury import JuryVerdict
from swag_bot.core.loop import LoopEvent
from swag_bot.core.reversibility import Reversibility
from swag_bot.interfaces import (
    ActionRequest,
    AutonomyLevel,
    ChatResponse,
    Message,
    StepStatus,
    ToolCall,
)
from tests.cli_output import visible
from tests.core.support import make_loop, plan_json, verdict
from tests.fakes import FakeLLMClient

runner = CliRunner()

_PAYMENT = "curl -X POST https://payments.example/transfer -d amount=500 -d to=attacker@example.com"


class ScriptedPrompter:
    """Records questions and jury blocks. Answers are popped, or None to decline."""

    def __init__(self, answers: list[str | None]) -> None:
        self._answers = list(answers)
        self.questions: list[str] = []
        self.blocks: list[str] = []

    def ask(self, request: ClarificationRequest) -> str | None:
        self.questions.append(request.question)
        if not self._answers:
            return None
        return self._answers.pop(0)

    def show_block(self, action: ActionRequest, verdict: JuryVerdict) -> None:
        del action
        self.blocks.append(verdict.reason)


class _Fixed:
    def __init__(self, label: Reversibility) -> None:
        self._label = label

    def classify(self, action: ActionRequest) -> Reversibility:
        del action
        return self._label


def _controller(
    prompter: ScriptedPrompter,
    judges: list[tuple[str, FakeLLMClient]] | None = None,
    *,
    samples: int = 1,
    jury: bool = True,
    classifier: object | None = None,
) -> tuple[EscalationController, FakeLLMClient]:
    session = FakeLLMClient()
    panel = judges if judges is not None else [("ollama/llama3.2", FakeLLMClient())]
    controller = EscalationController(
        EscalationSettings(enabled=True, samples=samples, jury=jury, jury_size=3),
        llm=session,
        judges=panel,  # type: ignore[arg-type]
        prompter=prompter,
        classifier=classifier,  # type: ignore[arg-type]
    )
    return controller, session


def _step(step_id: str, title: str, instruction: str = "") -> dict[str, object]:
    return {
        "id": step_id,
        "title": title,
        "instruction": instruction or title,
        "success_criteria": "the step is done",
    }


def test_low_confidence_step_asks_and_stops_without_guessing(tmp_path: Path) -> None:
    prompter = ScriptedPrompter([None])
    controller, _session = _controller(prompter, jury=False)
    loop, llm, sandbox, _memory = make_loop(
        tmp_path,
        [plan_json([_step("clean", "Clean the folder")])],
        max_attempts=1,
    )
    loop.escalation = controller
    events: list[LoopEvent] = []
    loop.on_event = events.append

    plan = loop.run("clean this up")

    assert plan.steps[0].status is StepStatus.FAILED
    assert prompter.questions
    question = prompter.questions[0]
    assert question.endswith("?")
    assert "clean this up" in question
    assert "Which paths" in question
    assert "Clean the folder" in question
    assert "Are you sure" not in question
    clarify = [event for event in events if event.kind == "clarify"]
    assert clarify and clarify[0].text == question
    assert loop.action_log == []
    assert sandbox.commands == []
    assert "Stopped to avoid guessing" in (loop.results["clean"].error or "")
    # The executor never ran, so the only model call after planning is the summary.
    assert not any(
        "The user answered" in (message.content or "")
        for messages in llm.messages
        for message in messages
    )


def test_an_answer_is_followed_instead_of_a_guess(tmp_path: Path) -> None:
    answer = "Delete only build/ and leave src/ alone."
    prompter = ScriptedPrompter([answer])
    controller, _session = _controller(prompter, jury=False)
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("clean", "Clean the folder")]),
            "Deleted build/ only.",
            verdict(True, "only build was removed"),
            "Cleaned build.",
        ],
        max_attempts=1,
    )
    loop.evidence_enabled = False
    loop.escalation = controller
    plan = loop.run("clean this up")
    assert plan.steps[0].status is StepStatus.DONE
    assert prompter.questions and "Which paths" in prompter.questions[0]
    blob = "\n".join((message.content or "") for messages in llm.messages for message in messages)
    assert answer in blob
    assert "Do not guess beyond it" in blob


def test_jury_blocks_a_payment_the_goal_did_not_ask_for(tmp_path: Path) -> None:
    reason = "This transfers money the goal never named."
    reject = json.dumps({"approve": False, "reason": reason})
    judge = FakeLLMClient([reject, reject, reject])
    prompter = ScriptedPrompter([])
    controller, _session = _controller(prompter, judges=[("ollama/llama3.2", judge)])
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("write", "Write ok.txt", "Write ok.txt containing ok")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(id="pay", name="run_shell", arguments={"command": _PAYMENT}),
                    ]
                )
            ),
            "The transfer was blocked.",
            verdict(False, "no payment was made"),
            "Blocked.",
        ],
        max_attempts=1,
    )
    loop.escalation = controller
    plan = loop.run("Write ok.txt containing the word ok")
    assert plan.steps[0].status is StepStatus.FAILED
    assert sandbox.commands == []
    assert not (sandbox.workdir / "ok.txt").exists()
    assert loop.action_log
    assert loop.action_log[0].approved is False
    assert loop.action_log[0].approver == "jury"
    assert "Jury blocked" in (loop.action_log[0].outcome or "")
    assert reason in (loop.action_log[0].outcome or "")
    assert prompter.blocks and reason in prompter.blocks[0]
    assert judge.messages
    assert controller.jury.judges[0][0] == "ollama/llama3.2"


def test_jury_does_not_touch_a_reversible_write(tmp_path: Path) -> None:
    judge = FakeLLMClient()
    prompter = ScriptedPrompter([])
    controller, _session = _controller(prompter, judges=[("ollama/llama3.2", judge)])
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("write", "Write hello.txt")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="w",
                            name="write_file",
                            arguments={"path": "hello.txt", "content": "hello"},
                        )
                    ]
                )
            ),
            "wrote hello.txt",
            verdict(True, "hello.txt contains hello"),
            "Wrote it.",
        ],
        autonomy=AutonomyLevel.AUTO,
    )
    loop.escalation = controller
    plan = loop.run("Write hello.txt containing hello")
    assert plan.steps[0].status is StepStatus.DONE
    assert sandbox.read_file("hello.txt") == "hello"
    assert judge.messages == []
    assert prompter.blocks == []
    assert prompter.questions == []


def test_compensable_action_skips_the_jury(tmp_path: Path) -> None:
    judge = FakeLLMClient()
    prompter = ScriptedPrompter([])
    controller, _session = _controller(
        prompter,
        judges=[("ollama/llama3.2", judge)],
        classifier=_Fixed(Reversibility.COMPENSABLE),
    )
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("pay", "Close the issue")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[ToolCall(id="c", name="run_shell", arguments={"command": _PAYMENT})]
                )
            ),
            "ran the compensable command",
            verdict(True, "the command ran"),
            "Done.",
        ],
        autonomy=AutonomyLevel.AUTO,
        max_attempts=1,
    )
    loop.escalation = controller
    plan = loop.run("Write ok.txt containing the word ok")
    assert plan.steps[0].status is StepStatus.DONE
    assert sandbox.commands == [_PAYMENT]
    assert judge.messages == []


def test_escalate_flag_prints_the_question_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLMClient([plan_json([_step("clean", "Clean the folder")]), "Stopped."])
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["run", "clean this up", "--escalate", "--output-dir", str(out), "--max-attempts", "1"],
        input="\n",
    )
    text = visible(result)
    assert result.exit_code == 1, text
    assert "Which paths" in text
    assert "clean this up" in text
    assert "Clarification needed" in text
    assert not (out / "build").exists()
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "failed" in summary.casefold()


def test_run_without_escalate_does_not_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLMClient(
        [
            plan_json([_step("write", "Write hello.txt")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="w",
                            name="write_file",
                            arguments={"path": "hello.txt", "content": "hello"},
                        )
                    ]
                )
            ),
            "wrote hello.txt",
            verdict(True, "hello.txt contains hello"),
            "Wrote it.",
        ]
    )
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            "clean this up",
            "--autonomy",
            "auto",
            "--output-dir",
            str(out),
            "--max-attempts",
            "1",
        ],
    )
    text = visible(result)
    assert result.exit_code == 0, text
    assert "Clarification needed" not in text
    assert (out / "hello.txt").read_text(encoding="utf-8") == "hello"
