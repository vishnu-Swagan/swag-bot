"""Small-model harness: probe a model, adapt the scaffold, escalate failures.

The loop does not import this package. ``swag run`` and ``swag model probe`` do.
"""

from __future__ import annotations

from swag_bot.harness.session import prepare_harness

__all__ = ["prepare_harness"]
