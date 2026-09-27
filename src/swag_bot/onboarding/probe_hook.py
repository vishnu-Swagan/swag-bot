"""Hook for the small-model harness. This package does not run it.

``swag model probe`` belongs to the harness work (PR #18). When that module
lands, ``small_model_probe_available`` becomes true and setup can point at
it. Until then, a model id with no size token is still allowed, and the
message tells the user to probe it later.
"""

from __future__ import annotations

import importlib


def small_model_probe_available() -> bool:
    """True when ``swag_bot.models.probe.probe_model`` can be imported."""
    try:
        module = importlib.import_module("swag_bot.models.probe")
    except ImportError:
        return False
    return callable(getattr(module, "probe_model", None))


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
