"""Wire uncertainty, the clarifying question, and the irreversible-action jury.

Off unless ``escalation.enabled`` is set or the run passes ``--escalate``.
A single local model is the normal case: self-consistency sampling stays at
one (no extra calls), and the jury reuses that model with separate prompts.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass

from swag_bot.config import EscalationSettings
from swag_bot.core.escalation_prompt import (
    ClarificationRequest,
    EscalationPrompter,
    RichEscalationPrompter,
)
from swag_bot.core.jury import Jury, JuryVerdict
from swag_bot.core.reversibility import (
    Reversibility,
    ReversibilityClassifier,
    StubReversibilityClassifier,
)
from swag_bot.core.uncertainty import UncertaintyEstimate, estimate_uncertainty
from swag_bot.interfaces import ActionRequest, LLMClient, Step

_QUIET = UncertaintyEstimate(
    uncertainty=0.0,
    confidence=1.0,
    signals=(),
    question="",
    should_escalate=False,
)

_SAMPLE_PROMPT = (
    "Reply with one sentence and no alternatives: the single next action for this step.\n"
    "Goal: {goal}\n"
    "Step: {title}\n"
    "Instruction: {instruction}"
)


@dataclass(frozen=True)
class JuryBlock:
    """An irreversible action the jury refused to let run."""

    reason: str
    verdict: JuryVerdict


class EscalationController:
    """Per-run gate. Safe to share across steps; prompts are serialized."""

    def __init__(
        self,
        settings: EscalationSettings,
        *,
        llm: LLMClient,
        judges: Sequence[tuple[str, LLMClient]],
        prompter: EscalationPrompter | None = None,
        classifier: ReversibilityClassifier | None = None,
    ) -> None:
        if not judges:
            raise ValueError("escalation needs at least one model")
        self.settings = settings
        self.llm = llm
        self.prompter = prompter if prompter is not None else RichEscalationPrompter()
        self.classifier = classifier if classifier is not None else StubReversibilityClassifier()
        self.jury = Jury(judges, size=settings.jury_size)
        self._goal = ""
        self._answers: dict[str, str] = {}
        self._observations: dict[str, str] = {}
        self._verdicts: dict[str, list[tuple[bool, str]]] = {}
        self._state = threading.Lock()
        self._prompt = threading.Lock()

    def bind_goal(self, goal: str) -> None:
        """Remember the user goal. Called once at the start of a run."""
        with self._state:
            self._goal = goal
            self._answers.clear()
            self._observations.clear()
            self._verdicts.clear()

    def estimate(self, step: Step, *, attempt: int) -> UncertaintyEstimate:
        """Score ``step`` from the signals collected so far."""
        if not self.settings.enabled:
            return _QUIET
        with self._state:
            goal = self._goal
            clarified = step.id in self._answers
            observation = self._observations.get(step.id, "")
            verdicts = tuple(self._verdicts.get(step.id, ()))
        samples: list[str] = []
        if self.settings.samples > 1 and attempt == 1 and not clarified:
            samples = self._sample(step, goal)
        return estimate_uncertainty(
            goal=goal,
            step_title=step.title,
            attempt=attempt,
            observation=observation,
            samples=samples,
            verdicts=verdicts,
            threshold=self.settings.uncertainty_threshold,
            clarified=clarified,
        )

    def ask(self, estimate: UncertaintyEstimate, step: Step) -> str | None:
        """Show the question. Remember a real answer so the goal is no longer vague."""
        request = ClarificationRequest(
            step_id=step.id,
            step_title=step.title,
            question=estimate.question,
            uncertainty=estimate.uncertainty,
            confidence=estimate.confidence,
            signals=estimate.signals,
        )
        with self._prompt:
            answer = self.prompter.ask(request)
        if answer:
            with self._state:
                self._answers[step.id] = answer
        return answer

    def note_observation(self, step_id: str, observation: str) -> None:
        """Keep the latest model text for the low-confidence signal."""
        with self._state:
            self._observations[step_id] = observation

    def note_verdict(self, step_id: str, passed: bool, reason: str) -> None:
        """Keep checker results for the disagreement and retry signals."""
        with self._state:
            self._verdicts.setdefault(step_id, []).append((passed, reason))

    def review_action(self, action: ActionRequest, *, step: Step) -> JuryBlock | None:
        """Jury an irreversible action. Return None when it may proceed.

        Reversible and compensable actions are not sent to the jury. A refused
        action is shown on the block card and must not run.
        """
        if not self.settings.enabled or not self.settings.jury:
            return None
        label = self.classifier.classify(action)
        if label is not Reversibility.IRREVERSIBLE:
            return None
        with self._state:
            goal = self._goal
        verdict = self.jury.review(action, goal=goal, step_title=step.title, reversibility=label)
        if verdict.approved:
            return None
        with self._prompt:
            self.prompter.show_block(action, verdict)
        return JuryBlock(reason=verdict.reason, verdict=verdict)

    def _sample(self, step: Step, goal: str) -> list[str]:
        prompt = _SAMPLE_PROMPT.format(
            goal=goal.strip() or "(empty)",
            title=step.title,
            instruction=step.instruction or step.title,
        )
        found: list[str] = []
        for _ in range(self.settings.samples):
            try:
                text = self.llm.complete(prompt).strip()
            except Exception:
                continue
            if text:
                found.append(text)
        return found


def build_escalation(
    settings: EscalationSettings,
    *,
    llm: LLMClient,
    judges: Sequence[tuple[str, LLMClient]] | None = None,
    prompter: EscalationPrompter | None = None,
    classifier: ReversibilityClassifier | None = None,
    session_label: str = "session",
) -> EscalationController | None:
    """Return a controller when escalation is on, otherwise None.

    An empty judge list uses ``llm`` once. That is the single-model path.
    """
    if not settings.enabled:
        return None
    panel = list(judges) if judges else [(session_label, llm)]
    if not panel:
        panel = [(session_label, llm)]
    return EscalationController(
        settings,
        llm=llm,
        judges=panel,
        prompter=prompter,
        classifier=classifier,
    )
