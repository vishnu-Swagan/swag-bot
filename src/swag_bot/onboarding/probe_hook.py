"""Hook for the small-model harness.

``swag model probe`` profiles the active model. When that command is
installed, setup tells the user to run it for a model id that does not
say its size.
"""

from __future__ import annotations

import importlib


def small_model_probe_available() -> bool:
    """True when ``swag model probe`` can profile a model."""
    try:
        module = importlib.import_module("swag_bot.harness.probe")
    except ImportError:
        return False
    return callable(getattr(module, "profile_model", None))


def unknown_size_note(model_id: str) -> str:
    """Sentence appended when a local model id does not say its size."""
    if small_model_probe_available():
        follow = "Run `swag model probe` before you trust it for a long task."
    else:
        follow = (
            "`swag model probe` is not in this install. "
            "When that command exists, run it before you trust a small local model."
        )
    return (
        f" The id {model_id!r} does not say how many parameters it has, "
        f"so it is allowed. {follow}"
    )
