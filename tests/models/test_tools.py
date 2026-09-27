"""Tool-call normalization and the JSON-in-text fallback."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from swag_bot.interfaces import Tool, ToolCall
from swag_bot.models.tools import (
    normalize_tool_calls,
    parse_tool_calls_from_text,
    tools_as_openai,
)


def test_openai_string_arguments_become_a_dict() -> None:
    calls = normalize_tool_calls(
        [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "add", "arguments": '{"a": 1, "b": 2}'},
            }
        ]
    )
    assert calls == [ToolCall(id="call_1", name="add", arguments={"a": 1, "b": 2})]


def test_ollama_dict_arguments_and_missing_id() -> None:
    calls = normalize_tool_calls(
        [{"function": {"name": "get_weather", "arguments": {"city": "Paris"}}}]
    )
    assert len(calls) == 1
    assert calls[0].name == "get_weather"
    assert calls[0].arguments == {"city": "Paris"}
    assert calls[0].id.startswith("call_")


def test_object_style_tool_call() -> None:
    class Function:
        name = "add"
        arguments = '{"a": 1}'

    class Call:
        id = "call_obj"
        function = Function()

    calls = normalize_tool_calls([Call()])
    assert calls[0].id == "call_obj"
    assert calls[0].arguments == {"a": 1}


def test_invalid_argument_json_raises() -> None:
    with pytest.raises(ValidationError):
        normalize_tool_calls([{"id": "1", "function": {"name": "add", "arguments": "[1, 2]"}}])


def test_fenced_json_tool_call() -> None:
    text = """I'll look that up.
```json
{"tool_calls":[{"name":"add","arguments":{"a":1,"b":2}}]}
```
"""
    calls = parse_tool_calls_from_text(text, allowed_names={"add"})
    assert len(calls) == 1
    assert calls[0].name == "add"
    assert calls[0].arguments == {"a": 1, "b": 2}


def test_raw_json_and_string_arguments() -> None:
    text = json.dumps({"name": "add", "arguments": '{"a": 3}'})
    calls = parse_tool_calls_from_text(text, allowed_names={"add"})
    assert calls[0].arguments == {"a": 3}


def test_prose_json_is_not_a_tool_call() -> None:
    text = 'Here is data: {"answer": 1, "name": "Ada"}'
    assert parse_tool_calls_from_text(text, allowed_names={"add"}) == []


def test_disallowed_tool_name_is_dropped() -> None:
    text = '{"tool_calls":[{"name":"other","arguments":{}}]}'
    assert parse_tool_calls_from_text(text, allowed_names={"add"}) == []


def test_broken_json_returns_nothing() -> None:
    assert parse_tool_calls_from_text("not json {", allowed_names={"add"}) == []
    assert parse_tool_calls_from_text("", allowed_names={"add"}) == []


def test_tools_as_openai_shape() -> None:
    tool = Tool(name="add", description="add two numbers", parameters={"type": "object"})
    spec = tools_as_openai([tool])
    assert spec[0]["type"] == "function"
    assert spec[0]["function"]["name"] == "add"
