"""Stand-in for the evidence ledger (feature #1, owned by another branch).

Dependent steps can cite evidence ids when a lookup is installed. Until that
ledger exists, ``NoEvidence`` reports none so handoff stays honest.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class EvidenceLookup(Protocol):
    """Ids of ledger entries produced while a step ran.

    The real ledger is not part of this branch. Callers pass a lookup when
    one is available and otherwise use ``NoEvidence``.
    """

    def ids_for_step(self, step_id: str) -> Sequence[str]:
        """Return evidence ids for ``step_id``. Empty when nothing was recorded."""
        ...


class NoEvidence:
    """Lookup that always reports no evidence."""

    def ids_for_step(self, step_id: str) -> Sequence[str]:
        del step_id
        return ()
