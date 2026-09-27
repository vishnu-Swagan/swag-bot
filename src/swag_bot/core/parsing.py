"""Parse JSON that a model wrapped in prose or a markdown fence."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class PlanParseError(ValueError):
    """The model did not return a plan or verdict we could read."""


def extract_json(text: str) -> Any:
    """Return the JSON value inside ``text``.

    Accepts a raw value, a fenced block, or prose that contains one object
    or array. Raises ``PlanParseError`` when nothing parses.
    """
    raw = (text or "").strip()
    if not raw:
        raise PlanParseError("the model returned an empty response")
    candidate = _FENCE.sub("", raw).strip()
    for blob in (candidate, _slice_json(candidate)):
        if not blob:
            continue
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            continue
    raise PlanParseError("the model response was not JSON")


def as_bool(value: Any) -> bool:
    """Coerce a model field to bool. The strings ``true`` and ``yes`` are true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1", "pass", "passed"}
    return bool(value)


def _slice_json(text: str) -> str:
    object_at = text.find("{")
    array_at = text.find("[")
    if object_at < 0 and array_at < 0:
        return ""
    if array_at >= 0 and (object_at < 0 or array_at < object_at):
        end = text.rfind("]")
        if end > array_at:
            return text[array_at : end + 1]
        return ""
    end = text.rfind("}")
    if object_at >= 0 and end > object_at:
        return text[object_at : end + 1]
    return ""
