"""Small-model harness: probe a model, adapt the scaffold, escalate failures.

The loop does not import this package. ``swag run`` and ``swag model probe`` do.

Imports stay lazy. Loading ``probe`` must not pull in ``core.cli``, which
imports this package back.
"""

from __future__ import annotations

from typing import Any

__all__ = ["prepare_harness"]


def __getattr__(name: str) -> Any:
    if name == "prepare_harness":
        from swag_bot.harness.session import prepare_harness

        return prepare_harness
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
