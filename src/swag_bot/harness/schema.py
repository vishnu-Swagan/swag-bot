"""JSON schemas for constrained planner, verifier, and probe output.

The schemas describe types and required keys. They do not contain sample
values. A small model that copies an example plan was failing real tasks by
returning ``"id": "short-id"`` instead of a plan for the goal.
"""

from __future__ import annotations

from typing import Any

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "instruction": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "instruction"],
            },
        }
    },
    "required": ["steps"],
}

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
        "replan": {"type": "boolean"},
    },
    "required": ["passed", "reason", "replan"],
}

PROBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "n": {"type": "integer"},
    },
    "required": ["ok", "n"],
}
