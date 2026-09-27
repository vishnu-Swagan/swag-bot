"""Portable run bundles and deterministic replay.

Import the public names from this package. Skill tests should call
``replay_run`` or ``BundleReplayer``. The on-disk format is
``docs/spec/run-bundle.md``.

This module stays light so ``core.loop`` can set the step context without
importing the replay implementation.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SPEC_ID",
    "SPEC_VERSION",
    "BundleReplayer",
    "ReplayReport",
    "RunReplayer",
    "export_bundle",
    "load_bundle",
    "replay_run",
]

_EXPORTS = {
    "SPEC_ID": ("swag_bot.core.bundle.spec", "SPEC_ID"),
    "SPEC_VERSION": ("swag_bot.core.bundle.spec", "SPEC_VERSION"),
    "ReplayReport": ("swag_bot.core.bundle.replay", "ReplayReport"),
    "RunReplayer": ("swag_bot.core.bundle.replay", "RunReplayer"),
    "BundleReplayer": ("swag_bot.core.bundle.replay", "BundleReplayer"),
    "replay_run": ("swag_bot.core.bundle.replay", "replay_run"),
    "load_bundle": ("swag_bot.core.bundle.store", "load_bundle"),
    "export_bundle": ("swag_bot.core.bundle.store", "export_bundle"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = __import__(module_name, fromlist=[attr])
    value = getattr(module, attr)
    globals()[name] = value
    return value
