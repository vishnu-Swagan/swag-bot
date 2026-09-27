"""Decide whether a step met its success criteria.

Machine checks run here, through the sandbox, before the model is asked.
The model sees the evidence ledger, not only the executor's claim. A pass
that cites nothing the ledger can support is unverified, never done. A failed
check is final for that attempt: the model's claim cannot override it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from swag_bot.core.checks import CheckRunner
from swag_bot.core.evidence import EvidenceLedger, current_attempt, ground_claim
from swag_bot.core.parsing import PlanParseError, as_bool, extract_json
from swag_bot.core.prompts import VERIFIER_SYSTEM
from swag_bot.interfaces import (
    ActionLogEntry,
    ApprovalPrompter,
    CheckResult,
    LLMClient,
    Message,
    PermissionPolicy,
    Sandbox,
    Step,
    StepResult,
)


@dataclass(frozen=True)
class Verdict:
    """The checker's decision for one attempt."""

    passed: bool
    reason: str
    replan: bool
    evidence_ids: tuple[str, ...] = ()
    unverified: bool = False
    check_results: tuple[CheckResult, ...] = ()


class Verifier:
    """Run acceptance checks, then ask the model about whatever checks cannot cover."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        model: str | None = None,
        sandbox: Sandbox | None = None,
        ledger: EvidenceLedger | None = None,
        policy: PermissionPolicy | None = None,
        prompter: ApprovalPrompter | None = None,
        on_action: Callable[[ActionLogEntry], None] | None = None,
        grounded: bool = True,
    ) -> None:
        self.llm = llm
        self.model = model
        self.ledger = ledger
        self.grounded = grounded
        self.runner: CheckRunner | None = None
        if grounded and sandbox is not None and ledger is not None:
            self.runner = CheckRunner(
                sandbox=sandbox,
                ledger=ledger,
                policy=policy,
                prompter=prompter,
                on_action=on_action,
            )

    def check(self, step: Step, result: StepResult) -> Verdict:
        if not self.grounded or self.runner is None or self.ledger is None:
            return self._model_verdict(step, result, evidence="")

        check_results = tuple(self.runner.run(step))
        failed = [item for item in check_results if not item.passed]
        if failed:
            ids: list[str] = []
            for item in failed:
                for evidence_id in item.evidence_ids:
                    if evidence_id not in ids:
                        ids.append(evidence_id)
            reason = "; ".join(item.detail for item in failed if item.detail)
            return Verdict(
                False,
                reason or "acceptance check failed",
                False,
                tuple(ids),
                False,
                check_results,
            )

        excerpt = self.ledger.excerpt(step.id, attempt=current_attempt.get())
        model = self._model_verdict(step, result, evidence=excerpt)
        passed, unverified, replan, reason, evidence_ids = ground_claim(
            claimed_pass=model.passed,
            reason=model.reason,
            replan=model.replan,
            cited=model.evidence_ids,
            check_results=check_results,
            evidence=self.ledger.for_step(step.id, attempt=current_attempt.get()),
        )
        return Verdict(passed, reason, replan, evidence_ids, unverified, check_results)

    def _model_verdict(self, step: Step, result: StepResult, *, evidence: str) -> Verdict:
        response = self.llm.chat(
            [
                Message.system(VERIFIER_SYSTEM),
                Message.user(_prompt(step, result, evidence)),
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
        return Verdict(passed, reason, replan, tuple(_evidence_ids(payload)))


def _evidence_ids(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("evidence_ids", payload.get("evidenceIds", []))
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in ids:
            ids.append(text)
    return ids


def _prompt(step: Step, result: StepResult, evidence: str) -> str:
    observation = result.observation or "(no observation)"
    error = result.error or "(none)"
    lines = [
        f"Step: {step.id} — {step.title}",
        f"Instruction:\n{step.instruction or step.title}",
        "The observation is the executor's claim. It is not evidence.",
        f"Observation:\n{_clip(observation)}",
        f"Error: {error}",
        "Evidence ledger (cite these ids; do not invent ids):",
        evidence or "(no evidence)",
    ]
    if step.checks:
        lines.append("Acceptance checks the harness already ran are reflected in the ledger.")
    return "\n".join(lines)


def _clip(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
