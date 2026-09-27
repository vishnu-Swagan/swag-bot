"""Step identity for the bundle recorder.

The loop sets these around one attempt. Tool wrappers read them. They stay
in this module so the loop does not import the replay implementation.
"""

from __future__ import annotations

from contextvars import ContextVar

current_step_id: ContextVar[str | None] = ContextVar("swag_bundle_step_id", default=None)
current_attempt: ContextVar[int] = ContextVar("swag_bundle_attempt", default=1)
