"""Read Swag Bot's ``_meta.swag`` block from an MCP tool or tool result.

The MCP SDK exposes this as ``meta`` on newer objects and as ``_meta`` in
the JSON shape. Only the ``swag`` object is returned. Unknown shapes become
an empty dict. This module does not decide trust; the taint firewall does.
"""

from __future__ import annotations

from typing import Any

_KEYS = ("risk", "trust", "source", "sinks")


def swag_meta(obj: Any) -> dict[str, Any]:
    """Return the ``swag`` metadata dict, or ``{}`` when it is absent."""
    raw = _meta_mapping(obj)
    swag = raw.get("swag") if raw else None
    if not isinstance(swag, dict):
        return {}
    picked: dict[str, Any] = {}
    for key in _KEYS:
        if key in swag:
            picked[key] = swag[key]
    return picked


def _meta_mapping(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        for key in ("meta", "_meta"):
            found = _as_dict(obj.get(key))
            if found:
                return found
        return {}
    for name in ("meta", "_meta"):
        found = _as_dict(getattr(obj, name, None))
        if found:
            return found
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            dumped = dump()
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            return _meta_mapping(dumped)
    return {}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            dumped = dump()
        except Exception:
            return {}
        if isinstance(dumped, dict):
            return dumped
    return {}
