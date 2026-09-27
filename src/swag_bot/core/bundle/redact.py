"""Strip secrets before they are written into a shareable bundle.

Redaction is idempotent: a second pass does not change the text. Non-secret
text, including ordinary words such as "token" with no value attached, is
left alone.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|credential|private[_-]?key)"
)

# Whole-match replacements. The entire match is a secret.
_WHOLE: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
)

# ``name=value`` and ``name: value``. Group 3 is the secret.
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization|credential)"
    r"\b(\s*[:=]\s*)(\S+)"
)

# Query-string credentials. Group 1 is the ``?key=`` prefix.
_QUERY = re.compile(r"(?i)([?&](?:api[_-]?key|token|secret|password|access_token)=)[^&\s]+")


def redact_text(value: str) -> str:
    """Replace secret-shaped substrings. Non-secret text is unchanged."""
    redacted = value
    for pattern in _WHOLE:
        redacted = pattern.sub(REDACTED, redacted)
    redacted = _QUERY.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)

    def _assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{REDACTED}"

    return _ASSIGNMENT.sub(_assignment, redacted)


def redact_value(value: Any) -> Any:
    """Recurse through JSON-like values.

    Secret-named keys are replaced wholesale. A secret string found in one
    field is also removed from other strings in the same value, so a key that
    was redacted cannot survive inside a nearby log line.
    """
    secrets = _secret_strings(value)
    return _apply(value, secrets)


def _secret_strings(value: Any) -> list[str]:
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            for pattern in _WHOLE:
                found.extend(pattern.findall(item))
            for match in _ASSIGNMENT.finditer(item):
                found.append(match.group(3))
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if isinstance(key, str) and _SECRET_KEY.search(key) and isinstance(child, str):
                    found.append(child)
                else:
                    walk(child)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    unique = {
        item
        for item in found
        if isinstance(item, str) and len(item) >= 8 and item != REDACTED
    }
    return sorted(unique, key=len, reverse=True)


def _apply(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        text = redact_text(value)
        for secret in secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        return text
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = _apply(item, secrets)
        return cleaned
    if isinstance(value, list):
        return [_apply(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_apply(item, secrets) for item in value]
    return value
