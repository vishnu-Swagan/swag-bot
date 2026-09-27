"""Verification-gated skill learning.

A succeeded run is distilled into a Cowork-compatible skill and kept in
quarantine. It becomes an active skill only after evidence-based verification
and a passing replay. See ``README.md``.
"""

from __future__ import annotations

from swag_bot.learning.adapters import StubEvidenceSource, StubRunReplayer
from swag_bot.learning.protocols import (
    CompletedRun,
    ReplayRequest,
    RunEvidenceSource,
    RunReplayer,
    VerifiedRunEvidence,
)
from swag_bot.learning.service import learn_from_run, promote_candidate, reject_candidate

__all__ = [
    "CompletedRun",
    "ReplayRequest",
    "RunEvidenceSource",
    "RunReplayer",
    "StubEvidenceSource",
    "StubRunReplayer",
    "VerifiedRunEvidence",
    "learn_from_run",
    "promote_candidate",
    "reject_candidate",
]
