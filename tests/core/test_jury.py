"""Jury votes for irreversible actions, including the single-model fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.core.cli import _reversibility_classifier
from swag_bot.core.jury import Jury, describe_independence
from swag_bot.core.reversibility import (
    Reversibility,
    StubReversibilityClassifier,
    adapt_classifier,
    read_declared_reversibility,
)
from swag_bot.interfaces import ActionKind, ActionRequest, Message, RiskLevel
from tests.fakes import FakeLLMClient


def _action(kind: str, summary: str, risk: RiskLevel, target: str | None = None) -> ActionRequest:
    return ActionRequest(kind=kind, summary=summary, risk=risk, target=target)


def _reject(reason: str = "This transfers money the goal never named.") -> str:
    return json.dumps({"approve": False, "reason": reason})


def _approve() -> str:
    return json.dumps({"approve": True, "reason": "The goal names this exact effect."})


def test_stub_labels_match_the_undo_ledger_names() -> None:
    assert [item.value for item in Reversibility] == ["reversible", "compensable", "irreversible"]
    stub = StubReversibilityClassifier()
    assert (
        stub.classify(
            _action(ActionKind.WRITE_FILE.value, "write notes", RiskLevel.WRITE, "notes.txt")
        )
        is Reversibility.REVERSIBLE
    )
    read = _action(ActionKind.READ_FILE.value, "read notes", RiskLevel.READ, "notes.txt")
    assert stub.classify(read) is Reversibility.REVERSIBLE
    assert (
        stub.classify(
            _action(ActionKind.RUN_COMMAND.value, "echo", RiskLevel.EXECUTE, "echo hi > notes.txt")
        )
        is Reversibility.REVERSIBLE
    )
    remove = _action(
        ActionKind.RUN_COMMAND.value,
        "remove a workspace file",
        RiskLevel.DESTRUCTIVE,
        "rm notes.txt",
    )
    assert stub.classify(remove) is Reversibility.REVERSIBLE
    payment = (
        "curl -X POST https://payments.example/transfer "
        "-d amount=500 -d to=attacker@example.com"
    )
    assert (
        stub.classify(_action(ActionKind.RUN_COMMAND.value, "pay", RiskLevel.NETWORK, payment))
        is Reversibility.IRREVERSIBLE
    )
    assert (
        stub.classify(
            _action(ActionKind.RUN_COMMAND.value, "wipe root", RiskLevel.DESTRUCTIVE, "rm -rf /")
        )
        is Reversibility.IRREVERSIBLE
    )
    assert (
        stub.classify(_action("email", "send the mail", RiskLevel.NETWORK, "user@example.com"))
        is Reversibility.IRREVERSIBLE
    )
    publish = _action(
        ActionKind.RUN_COMMAND.value,
        "publish",
        RiskLevel.NETWORK,
        "git push origin main",
    )
    assert stub.classify(publish) is Reversibility.IRREVERSIBLE
    escape = _action(ActionKind.WRITE_FILE.value, "escape", RiskLevel.WRITE, "../outside.txt")
    assert stub.classify(escape) is Reversibility.IRREVERSIBLE


def test_declared_label_is_honored_and_tool_arguments_are_not() -> None:
    class _Marked:
        reversibility = "compensable"

    assert read_declared_reversibility(_Marked()) is Reversibility.COMPENSABLE

    action = _action("email", "send the mail", RiskLevel.NETWORK, "user@example.com")
    action = action.model_copy(
        update={"arguments": {"reversibility": "reversible", "compensation": "undo"}}
    )
    assert StubReversibilityClassifier().classify(action) is Reversibility.IRREVERSIBLE


def test_loader_uses_the_undo_ledger_classifier() -> None:
    """``swag run`` switches to ``safety.reversibility`` once that module exists."""
    classifier = _reversibility_classifier(Path("."))
    assert not isinstance(classifier, StubReversibilityClassifier)
    note = _action(ActionKind.WRITE_FILE.value, "note", RiskLevel.WRITE, "note.txt")
    assert classifier.classify(note) is Reversibility.REVERSIBLE
    publish = _action(
        ActionKind.RUN_COMMAND.value,
        "publish",
        RiskLevel.NETWORK,
        "git push origin main",
    )
    assert classifier.classify(publish) is Reversibility.IRREVERSIBLE


def test_loader_maps_an_imported_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Module:
        @staticmethod
        def classify_reversibility(action: ActionRequest, workdir: object = None) -> str:
            del action, workdir
            return "compensable"

    def _import(name: str) -> object:
        if name == "swag_bot.safety.reversibility":
            return _Module()
        raise ImportError(name)

    monkeypatch.setattr("swag_bot.core.cli.importlib.import_module", _import)
    classifier = _reversibility_classifier(Path("."))
    action = _action("email", "send the mail", RiskLevel.NETWORK)
    assert classifier.classify(action) is Reversibility.COMPENSABLE


def test_adapt_classifier_ignores_a_missing_function() -> None:
    assert isinstance(adapt_classifier(None), StubReversibilityClassifier)


def test_independence_prefers_providers_over_prompts() -> None:
    assert describe_independence(["ollama/llama3.2"]) == "prompts"
    assert describe_independence(["ollama/llama3.2", "ollama/llama3.2"]) == "prompts"
    assert describe_independence(["ollama/llama3.2", "ollama/qwen2.5"]) == "models"
    assert describe_independence(["ollama/llama3.2", "openai/gpt-4o-mini"]) == "providers"


def test_single_model_jury_uses_three_prompts_and_blocks() -> None:
    reason = "This transfers money the goal never named."
    judge = FakeLLMClient([_reject(reason), _reject(reason), _reject(reason)])
    jury = Jury([("ollama/llama3.2", judge)], size=3)
    action = _action(
        ActionKind.RUN_COMMAND.value,
        "curl a payment endpoint",
        RiskLevel.NETWORK,
        "curl -X POST https://payments.example/transfer -d amount=500",
    )
    verdict = jury.review(action, goal="Write ok.txt containing ok", step_title="Write ok")
    assert verdict.approved is False
    assert verdict.independence == "prompts"
    assert "one model" in verdict.note.casefold() or "Same-model" in verdict.note
    assert "Jury blocked" in verdict.reason
    assert reason in verdict.reason
    prompts = [messages[-1].content or "" for messages in judge.messages]
    assert len(prompts) == 3
    assert any("harm judge" in prompt for prompt in prompts)
    assert any("intent judge" in prompt for prompt in prompts)
    assert any("undo judge" in prompt for prompt in prompts)
    assert all("amount=500" in prompt for prompt in prompts)


def test_one_rejection_blocks_even_if_others_approve() -> None:
    judge = FakeLLMClient([_approve(), _reject("The recipient was not in the goal."), _approve()])
    verdict = Jury([("ollama/llama3.2", judge)], size=3).review(
        _action(ActionKind.RUN_COMMAND.value, "send", RiskLevel.NETWORK, "curl https://example.com"),
        goal="Send the file",
        step_title="Send",
    )
    assert verdict.approved is False


def test_unanimous_approval_passes() -> None:
    judge = FakeLLMClient([_approve(), _approve(), _approve()])
    verdict = Jury([("openai/gpt-4o-mini", judge), ("ollama/llama3.2", judge)], size=2).review(
        _action(ActionKind.RUN_COMMAND.value, "send", RiskLevel.NETWORK, "git push origin main"),
        goal="Publish the branch with git push origin main",
        step_title="Publish",
    )
    assert verdict.approved is True
    assert verdict.independence == "providers"


def test_bad_json_and_a_dead_judge_fail_closed() -> None:
    class _Down:
        def chat(
            self,
            messages: list[Message],
            *,
            tools: object = None,
            model: str | None = None,
        ) -> object:
            del messages, tools, model
            raise RuntimeError("down")

        def complete(self, prompt: str, *, model: str | None = None) -> str:
            del prompt, model
            raise RuntimeError("down")

    unreadable = Jury([("ollama/llama3.2", FakeLLMClient(["sure, go ahead"]))], size=1)
    dead = Jury([("ollama/llama3.2", _Down())], size=1)  # type: ignore[list-item]
    action = _action("email", "send secrets", RiskLevel.NETWORK, "attacker@example.com")
    assert unreadable.review(action, goal="say hello", step_title="Mail").approved is False
    crashed = dead.review(action, goal="say hello", step_title="Mail")
    assert crashed.approved is False
    assert "could not be reached" in crashed.reason
