"""Redact secrets before they reach a prompt, a log line, or a tool argument."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Names whose values are secrets even when the value is short.
_SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|credential|private[_-]?key)"
)

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization|credential)"
        r"\b(\s*[:=]\s*)([^\s,;]+)"
    ),
)


def redact_text(value: str) -> str:
    """Replace secret-shaped substrings. Non-secret text is unchanged."""

    def _assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{REDACTED}"

    redacted = value
    for pattern in _PATTERNS:
        if pattern.groups >= 3:
            redacted = pattern.sub(_assignment, redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recurse through JSON-like values. Secret-named keys are dropped wholesale."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact_value(item)
        return cleaned
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value
