"""Shared generation limits for local model requests.

A CPU at about 10 tokens per second cannot finish a 4096-token reply inside
the harness timeout. The default cap is short. A timed-out retry asks for
an even shorter reply instead of sending the same request again.
"""

from __future__ import annotations

from collections.abc import Sequence

from swag_bot.interfaces import Message

# Keep this aligned with ``ModelSettings.num_predict`` and ``LOCAL_PREDICT_CAP``.
DEFAULT_NUM_PREDICT = 1024
RETRY_PREDICT_FLOOR = 256
CONCISE_NUDGE = "Be concise. Reply briefly and do not repeat the question."


def retry_num_predict(current: int | None) -> int:
    """A shorter cap for the single timeout retry."""
    base = current if current is not None and current > 0 else DEFAULT_NUM_PREDICT
    lowered = max(RETRY_PREDICT_FLOOR, base // 2)
    if current is not None and lowered >= current > RETRY_PREDICT_FLOOR:
        return RETRY_PREDICT_FLOOR
    return lowered


def concise_messages(messages: Sequence[Message]) -> list[Message]:
    """The same turn plus a nudge so the retry is not an identical request."""
    return [*messages, Message.user(CONCISE_NUDGE)]
