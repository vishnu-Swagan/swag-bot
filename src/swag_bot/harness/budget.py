"""Cost and latency budget for escalating one failing step.

Reserving a slot in ``allow`` keeps concurrent steps from all escalating
past the cap. ``charge`` records the time the attempt actually used so a
later step sees what is left.
"""

from __future__ import annotations

import threading


class EscalationBudget:
    """In-memory budget for a single run. It is not persisted."""

    def __init__(
        self,
        *,
        max_escalations: int,
        max_extra_seconds: float,
        max_cost_usd: float,
    ) -> None:
        self.max_escalations = max_escalations
        self.max_extra_seconds = max_extra_seconds
        self.max_cost_usd = max_cost_usd
        self.used_escalations = 0
        self.used_seconds = 0.0
        self.used_cost_usd = 0.0
        self._lock = threading.Lock()

    def allow(self, *, estimated_seconds: float, estimated_cost_usd: float) -> bool:
        """Reserve one escalation when the estimate fits. False leaves the step put."""
        with self._lock:
            if self.max_escalations <= 0:
                return False
            if self.used_escalations >= self.max_escalations:
                return False
            if self.used_seconds + estimated_seconds > self.max_extra_seconds:
                return False
            if self.used_cost_usd + estimated_cost_usd > self.max_cost_usd + 1e-9:
                return False
            self.used_escalations += 1
            self.used_cost_usd += estimated_cost_usd
            return True

    def charge(self, seconds: float) -> None:
        """Add the measured duration of an escalation that was allowed."""
        with self._lock:
            self.used_seconds += max(0.0, seconds)
