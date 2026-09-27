"""Normalize provider tool calls and parse the JSON-in-text fallback.

Native tool calls arrive as OpenAI-style objects (LiteLLM) or Ollama
function objects. Arguments may be a dict or a JSON string; ``ToolCall``
stores a dict either way. Models that cannot call tools are asked to emit
a single JSON object, and ``parse_tool_calls_from_text`` reads it back.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from swag_bot.interfaces import Tool, ToolCall

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_INSTRUCTION = (
    "You can call tools. When you need one, reply with only a JSON object "
    'of this shape and no other text: {"tool_calls":[{"name":"TOOL_NAME",'
    '"arguments":{}}]}. Arguments must be a JSON object. If you do not need '
    "a tool, reply with normal text and do not emit that JSON."
)


def new_tool_call_id() -> str:
    """An id for a tool call the provider did not number."""
    return f"call_{uuid4().hex[:16]}"


def tools_as_openai(tools: Sequence[Tool]) -> list[dict[str, Any]]:
    """Tool definitions in the shape Ollama and LiteLLM both accept."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


def json_tool_instruction(tools: Sequence[Tool]) -> str:
    """System text that asks a model to emit tool calls as JSON."""
    specs = [
        {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
        for tool in tools
    ]
    return _INSTRUCTION + "\nAvailable tools:\n" + json.dumps(specs)


def normalize_tool_calls(raw_calls: Any) -> list[ToolCall]:
    """Turn a provider tool-call list into ``ToolCall`` values.

    Objects and dicts are both accepted. Entries with no function name are
    skipped. Invalid argument JSON raises ``ValueError`` from ``ToolCall``.
    """
    if not raw_calls:
        return []
    if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
        raise ValueError("tool calls must be a list")
    normalized: list[ToolCall] = []
    for raw in raw_calls:
        call = _one_tool_call(raw)
        if call is not None:
            normalized.append(call)
    return normalized


def parse_tool_calls_from_text(
    text: str | None,
    *,
    allowed_names: set[str] | None = None,
) -> list[ToolCall]:
    """Extract tool calls from assistant text.

    Fenced JSON blocks are tried first, then every JSON object or array in
    the text. A value counts only when it has the tool-call shape. When
    ``allowed_names`` is set, calls whose name is not in that set are dropped
    so an ordinary JSON answer is not treated as a tool invocation.
    """
    if not text or not text.strip():
        return []
    found: list[ToolCall] = []
    for value in _json_values(text):
        try:
            calls = _calls_from_json_value(value)
        except (ValueError, ValidationError):
            continue
        if allowed_names is not None:
            calls = [call for call in calls if call.name in allowed_names]
        if calls:
            found.extend(calls)
            break
    return found


def apply_text_tool_calls(content: str | None, calls: list[ToolCall]) -> str | None:
    """Drop content that is only the tool-call JSON. Keep surrounding prose."""
    if not calls or not content:
        return content
    stripped = content.strip()
    # If the whole message is a fence or a JSON value, the tool calls are the message.
    if stripped.startswith("{") or stripped.startswith("[") or stripped.startswith("```"):
        return None
    return content


def _one_tool_call(raw: Any) -> ToolCall | None:
    data = _as_mapping(raw)
    if data is None:
        return None
    function = data.get("function")
    function_data = _as_mapping(function) if function is not None else None
    name = _string(data.get("name"))
    arguments: Any = data.get("arguments", {})
    if function_data is not None:
        name = _string(function_data.get("name")) or name
        if "arguments" in function_data:
            arguments = function_data.get("arguments")
    if not name:
        return None
    call_id = _string(data.get("id")) or new_tool_call_id()
    if arguments is None:
        arguments = {}
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _calls_from_json_value(value: Any) -> list[ToolCall]:
    if isinstance(value, list):
        return normalize_tool_calls(value)
    if not isinstance(value, dict):
        return []
    if "tool_calls" in value and isinstance(value["tool_calls"], list):
        return normalize_tool_calls(value["tool_calls"])
    if "function" in value or "name" in value:
        call = _one_tool_call(value)
        return [call] if call is not None else []
    return []


def _json_values(text: str) -> list[Any]:
    values: list[Any] = []
    for match in _FENCE.finditer(text):
        parsed = _loads(match.group(1))
        if parsed is not _MISSING:
            values.append(parsed)
    decoder = json.JSONDecoder()
    index = 0
    length = len(text)
    while index < length:
        brace = text.find("{", index)
        bracket = text.find("[", index)
        starts = [pos for pos in (brace, bracket) if pos >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        values.append(value)
        index = max(end, start + 1)
    return values


_MISSING = object()


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _MISSING


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if value is None or isinstance(value, (str, bytes, int, float, bool, list)):
        return None
    # LiteLLM / OpenAI SDK objects expose the fields we need as attributes.
    name = getattr(value, "name", None)
    function = getattr(value, "function", None)
    if name is None and function is None and not hasattr(value, "id"):
        return None
    data: dict[str, Any] = {}
    for key in ("id", "name", "arguments", "function"):
        if hasattr(value, key):
            data[key] = getattr(value, key)
    return data


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
