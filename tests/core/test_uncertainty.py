"""Cheap uncertainty signals and the clarifying question."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from swag_bot.config import EscalationSettings, Settings, load_settings, save_settings
from swag_bot.core.escalation import build_escalation
from swag_bot.core.escalation_prompt import ClarificationRequest, RichEscalationPrompter
from swag_bot.core.jury import JuryVerdict
from swag_bot.core.uncertainty import Signal, estimate_uncertainty, suggest_threshold
from swag_bot.errors import ConfigError
from swag_bot.interfaces import ActionKind, ActionRequest, RiskLevel, Step
from tests.fakes import FakeLLMClient


def test_ambiguous_goal_asks_which_paths() -> None:
    estimate = estimate_uncertainty(goal="clean this up", step_title="Clean the folder")
    assert estimate.should_escalate
    assert estimate.confidence < estimate.uncertainty or estimate.uncertainty >= 0.6
    assert estimate.question.endswith("?")
    assert "clean this up" in estimate.question
    assert "Clean the folder" in estimate.question
    assert "Which paths" in estimate.question
    assert "Are you sure" not in estimate.question
    assert any(signal.name == "ambiguous_goal" for signal in estimate.signals)


def test_two_alternatives_are_named_in_the_question() -> None:
    goal = "rename notes.md to final.md or delete it"
    estimate = estimate_uncertainty(goal=goal, step_title="Rename or delete")
    assert estimate.should_escalate
    assert "rename notes.md to final.md" in estimate.question
    assert "delete it" in estimate.question
    assert estimate.question.endswith("?")


def test_concrete_goal_does_not_escalate() -> None:
    for goal in (
        "Write hello.txt containing the word hi",
        "Summarize the files in this directory",
        "Run the tests in tests/core",
    ):
        estimate = estimate_uncertainty(goal=goal, step_title="Do the step")
        assert estimate.should_escalate is False, goal
        assert estimate.question == ""
        assert estimate.uncertainty == 0.0


def test_low_confidence_output_quotes_the_hedge() -> None:
    observation = "I'm not sure whether to overwrite report.md or append to it."
    estimate = estimate_uncertainty(
        goal="Update report.md with the totals",
        step_title="Update the report",
        observation=observation,
    )
    assert estimate.should_escalate
    assert any(signal.name == "low_confidence_output" for signal in estimate.signals)
    assert "report.md" in estimate.question
    assert "not sure" in estimate.question.casefold()
    assert estimate.question.endswith("?")


def test_explicit_low_confidence_escalates_and_high_confidence_does_not() -> None:
    low = estimate_uncertainty(
        goal="Write report.md",
        step_title="Write",
        observation="confidence: 0.2",
    )
    high = estimate_uncertainty(
        goal="Write report.md",
        step_title="Write",
        observation="confidence: 0.95",
    )
    assert low.should_escalate
    assert high.should_escalate is False


def test_disagreeing_samples_ask_which_reading() -> None:
    estimate = estimate_uncertainty(
        goal="Write notes.md with the meeting agenda",
        step_title="Write the notes",
        samples=(
            "Write notes.md with the agenda",
            "Email the agenda to every customer",
        ),
    )
    assert estimate.should_escalate
    assert any(signal.name == "self_consistency" for signal in estimate.signals)
    assert "Write notes.md with the agenda" in estimate.question
    assert "Email the agenda to every customer" in estimate.question


def test_identical_samples_add_no_disagreement() -> None:
    estimate = estimate_uncertainty(
        goal="Write notes.md with the meeting agenda",
        step_title="Write the notes",
        samples=("Write notes.md with the agenda", "Write notes.md with the agenda"),
    )
    assert estimate.signals == ()
    assert estimate.should_escalate is False


def test_verifier_disagreement_names_both_reasons() -> None:
    estimate = estimate_uncertainty(
        goal="Write report.md",
        step_title="Write the report",
        verdicts=((True, "the file exists"), (False, "the total is missing")),
    )
    assert estimate.should_escalate
    assert "disagreed" in estimate.question
    assert "the file exists" in estimate.question
    assert "the total is missing" in estimate.question


def test_retry_asks_what_should_change() -> None:
    first = estimate_uncertainty(
        goal="Write report.md",
        step_title="Write the report",
        attempt=1,
        verdicts=((False, "the total is missing"),),
    )
    second = estimate_uncertainty(
        goal="Write report.md",
        step_title="Write the report",
        attempt=2,
        verdicts=((False, "the total is missing"),),
    )
    assert first.should_escalate is False
    assert second.should_escalate
    assert "the total is missing" in second.question
    assert "What should change" in second.question


def test_threshold_can_silence_a_vague_goal() -> None:
    quiet = estimate_uncertainty(goal="clean this up", step_title="Clean", threshold=0.99)
    loud = estimate_uncertainty(goal="clean this up", step_title="Clean", threshold=0.5)
    assert quiet.should_escalate is False
    assert loud.should_escalate


def test_clarified_goal_drops_the_ambiguous_signal() -> None:
    estimate = estimate_uncertainty(
        goal="clean this up",
        step_title="Clean",
        clarified=True,
    )
    assert estimate.should_escalate is False


def test_missing_signals_do_not_crash() -> None:
    estimate = estimate_uncertainty(goal="", step_title="", samples=(), verdicts=())
    assert estimate.should_escalate is False
    assert estimate.confidence == 1.0


def test_suggest_threshold_uses_the_labeled_misses() -> None:
    assert suggest_threshold(()) == 0.6
    assert suggest_threshold([0.2, 0.4, 0.9], alpha=0.0) == 0.2
    assert suggest_threshold([0.2, 0.4, 0.9], alpha=1.0) == 0.9


def test_sampling_uses_the_session_model_and_can_escalate() -> None:
    llm = FakeLLMClient(
        [
            "Write notes.md with the agenda",
            "Email the agenda to every customer",
        ]
    )
    settings = EscalationSettings(enabled=True, samples=2, jury=False)
    controller = build_escalation(settings, llm=llm, session_label="ollama/llama3.2")
    assert controller is not None
    controller.bind_goal("Write notes.md with the meeting agenda")
    estimate = controller.estimate(Step(id="notes", title="Write the notes"), attempt=1)
    assert len(llm.messages) == 2
    assert estimate.should_escalate
    assert "Email the agenda" in estimate.question


def test_disabled_settings_build_nothing() -> None:
    assert EscalationSettings().enabled is False
    assert build_escalation(EscalationSettings(), llm=FakeLLMClient()) is None


def test_config_round_trip_and_bad_threshold(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    settings = Settings(
        escalation=EscalationSettings(enabled=True, uncertainty_threshold=0.4, samples=2)
    )
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.escalation.enabled is True
    assert loaded.escalation.uncertainty_threshold == 0.4
    assert loaded.escalation.samples == 2
    assert loaded.escalation.jury is True
    path.write_text("[escalation]\nuncertainty_threshold = 1.4\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_prompter_shows_the_question_and_stops_on_an_empty_answer() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, no_color=True, width=100)
    answers = iter(["", "Delete only build/ and leave src/ alone."])

    def ask(prompt: str) -> str:
        assert prompt == "Your answer"
        return next(answers)

    prompter = RichEscalationPrompter(console=console, ask=ask)
    request = ClarificationRequest(
        step_id="clean",
        step_title="Clean the folder",
        question="Which paths should I touch, and what should I leave alone?",
        uncertainty=0.84,
        confidence=0.16,
        signals=(Signal("ambiguous_goal", 0.84, "clean this up"),),
    )
    assert prompter.ask(request) is None
    assert prompter.ask(request) == "Delete only build/ and leave src/ alone."
    text = buffer.getvalue()
    assert "Clarification needed" in text
    assert "Which paths should I touch" in text
    assert "ambiguous_goal" in text
    assert "Stopped (no answer)" in text


def test_prompter_treats_end_of_input_as_no_answer() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, no_color=True, width=80)

    def ask(prompt: str) -> str:
        del prompt
        raise EOFError

    prompter = RichEscalationPrompter(console=console, ask=ask)
    request = ClarificationRequest(
        step_id="clean",
        step_title="Clean",
        question="Which paths should I touch?",
        uncertainty=0.8,
        confidence=0.2,
        signals=(),
    )
    assert prompter.ask(request) is None
    assert "will not guess" in buffer.getvalue()


def test_block_card_matches_the_approval_layout() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, no_color=True, width=160)
    prompter = RichEscalationPrompter(console=console, ask=lambda _prompt: "")
    action = ActionRequest(
        kind=ActionKind.RUN_COMMAND.value,
        summary="curl a payment endpoint",
        risk=RiskLevel.NETWORK,
        target="curl https://payments.example/transfer",
    )
    verdict = JuryVerdict(
        approved=False,
        votes=(),
        independence="prompts",
        note="Same-model judges share errors.",
        reversibility="irreversible",
    )
    prompter.show_block(action, verdict)
    text = buffer.getvalue()
    assert "Blocked by jury" in text
    assert "curl a payment endpoint" in text
    assert "network" in text
    assert "irreversible" in text
    assert "prompts" in text
    assert "Same-model judges share errors." in text
