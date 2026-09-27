"""The promotion gate refuses anything short of evidence plus a passing replay."""

from __future__ import annotations

from swag_bot.learning.adapters import StubEvidenceSource, StubRunReplayer
from swag_bot.learning.gate import decide
from swag_bot.learning.protocols import (
    ReplayOutcome,
    ReplayRequest,
    ReplayResult,
    RunEvidenceSource,
    RunReplayer,
    VerifiedRunEvidence,
)


def test_stubs_never_pass_and_match_the_protocols() -> None:
    evidence_source = StubEvidenceSource()
    replayer = StubRunReplayer()
    assert isinstance(evidence_source, RunEvidenceSource)
    assert isinstance(replayer, RunReplayer)
    evidence = evidence_source.evidence_for("run-1")
    replay = replayer.replay(ReplayRequest(run_id="run-1", goal="Create hello.txt", skill_name="s"))
    assert evidence.accepted() is False
    assert replay.outcome is ReplayOutcome.UNAVAILABLE
    decision = decide("run-1", evidence, replay)
    assert decision.allowed is False
    assert "not verified" in decision.explain()
    assert "unavailable" in decision.explain()


def test_verified_flag_without_evidence_ids_is_refused() -> None:
    evidence = VerifiedRunEvidence(run_id="run-1", verified=True, evidence_ids=["  ", ""])
    replay = ReplayResult(run_id="run-1", outcome=ReplayOutcome.PASSED, goal="Create hello.txt")
    decision = decide("run-1", evidence, replay)
    assert evidence.accepted() is False
    assert decision.allowed is False
    assert "cites no evidence" in decision.explain()


def test_unverified_run_is_refused_even_when_replay_passes() -> None:
    evidence = VerifiedRunEvidence(run_id="run-1", verified=False, evidence_ids=["ev-1"])
    replay = ReplayResult(run_id="run-1", outcome=ReplayOutcome.PASSED, goal="Create hello.txt")
    decision = decide("run-1", evidence, replay)
    assert decision.allowed is False
    assert "not verified" in decision.explain()


def test_verified_run_is_refused_when_replay_fails() -> None:
    evidence = VerifiedRunEvidence(run_id="run-1", verified=True, evidence_ids=["ev-1"])
    replay = ReplayResult(run_id="run-1", outcome=ReplayOutcome.FAILED, goal="Create hello.txt")
    decision = decide("run-1", evidence, replay)
    assert evidence.accepted() is True
    assert decision.allowed is False
    assert "replay failed" in decision.explain()


def test_gate_opens_only_when_both_halves_accept_the_same_run() -> None:
    evidence = VerifiedRunEvidence(
        run_id="run-1",
        verified=True,
        evidence_ids=["ev-1", " ev-2 "],
        detail="checks cited the ledger",
    )
    replay = ReplayResult(run_id="run-1", outcome=ReplayOutcome.PASSED, varied=True, goal="varied")
    decision = decide("run-1", evidence, replay)
    assert decision.allowed is True
    assert evidence.cited_ids() == ["ev-1", "ev-2"]

    other = decide("run-2", evidence, replay)
    assert other.allowed is False
    assert "different run" in other.explain()
