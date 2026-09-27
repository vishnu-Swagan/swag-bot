"""Ask the model whether a step met its success criteria."""

from __future__ import annotations

from dataclasses import dataclass

from swag_bot.core.parsing import PlanParseError, as_bool, extract_json
from swag_bot.core.prompts import VERIFIER_SYSTEM
from swag_bot.interfaces import LLMClient, Message, Step, StepResult


@dataclass(frozen=True)
class Verdict:
    """The checker's decision for one attempt."""

    passed: bool
    reason: str
    replan: bool


class Verifier:
    """One LLM call per check. A missing JSON verdict is a failed check."""

    def __init__(self, llm: LLMClient, *, model: str | None = None) -> None:
        self.llm = llm
        self.model = model

    def check(self, step: Step, result: StepResult) -> Verdict:
        response = self.llm.chat(
            [
                Message.system(VERIFIER_SYSTEM),
                Message.user(_prompt(step, result)),
            ],
            model=self.model,
        )
        try:
            payload = extract_json(response.message.content or "")
        except PlanParseError:
            return Verdict(False, "The verifier did not return a JSON object.", False)
        if not isinstance(payload, dict):
            return Verdict(False, "The verifier did not return a JSON object.", False)
        passed = as_bool(payload.get("passed"))
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            reason = "passed" if passed else "the check failed"
        replan = False if passed else as_bool(payload.get("replan"))
        return Verdict(passed, reason, replan)


def _prompt(step: Step, result: StepResult) -> str:
    observation = result.observation or "(no observation)"
    error = result.error or "(none)"
    return "\n".join(
        [
            f"Step: {step.id} — {step.title}",
            f"Instruction:\n{step.instruction or step.title}",
            f"Observation:\n{_clip(observation)}",
            f"Error: {error}",
        ]
    )


def _clip(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
