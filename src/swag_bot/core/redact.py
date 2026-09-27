"""Strip likely secrets before they are stored on an action log entry."""

from __future__ import annotations

import re
from typing import Any

_SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|authorization|credential|passwd)"
)
_SECRET_INLINE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|authorization|credential|passwd)"
    r"\s*[:=]\s*)(\S+)|(bearer\s+)(\S+)"
)


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with secret-shaped fields replaced."""
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key):
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_known(text: str, original: dict[str, Any], redacted: dict[str, Any]) -> str:
    """Remove secret values that were redacted out of ``original`` arguments."""
    cleaned = text
    for key, value in original.items():
        if redacted.get(key) == "[redacted]" and isinstance(value, str) and len(value) >= 4:
            cleaned = cleaned.replace(value, "[redacted]")
    return redact_text(cleaned)


def redact_text(text: str) -> str:
    """Replace inline ``key=value`` and ``Bearer`` secrets."""

    def _replace(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}[redacted]"
        return f"{match.group(3)}[redacted]"

    return _SECRET_INLINE.sub(_replace, text)
