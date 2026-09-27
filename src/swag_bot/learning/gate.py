"""The promotion gate. Both halves must pass, or the skill stays quarantined."""

from __future__ import annotations

from dataclasses import dataclass

from swag_bot.learning.protocols import ReplayOutcome, ReplayResult, VerifiedRunEvidence


@dataclass(frozen=True)
class GateDecision:
    """Whether a candidate may become an active skill."""

    allowed: bool
    reasons: tuple[str, ...]

    def explain(self) -> str:
        """One line a person can read."""
        if self.allowed:
            return "verification and replay passed"
        return "; ".join(self.reasons)


def decide(run_id: str, evidence: VerifiedRunEvidence, replay: ReplayResult) -> GateDecision:
    """Allow promotion only when evidence and replay both accept this run.

    An unverified run is refused even if the replay passed. A verified run
    is refused when the replay failed or never ran. A boolean ``verified``
    with no evidence ids is refused.
    """
    reasons: list[str] = []
    if evidence.run_id != run_id:
        reasons.append("evidence is for a different run")
    if not evidence.verified:
        reasons.append("run is not verified")
    if not evidence.cited_ids():
        reasons.append("verification cites no evidence")
    if replay.run_id != run_id:
        reasons.append("replay is for a different run")
    if replay.outcome is ReplayOutcome.FAILED:
        reasons.append("replay failed")
    elif replay.outcome is ReplayOutcome.UNAVAILABLE:
        reasons.append("replay is unavailable")
    elif replay.outcome is not ReplayOutcome.PASSED:
        reasons.append("replay did not pass")
    return GateDecision(allowed=not reasons, reasons=tuple(reasons))
