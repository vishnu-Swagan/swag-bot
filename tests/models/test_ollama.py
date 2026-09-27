"""Ollama client with a scripted HTTP transport. No sockets."""

from __future__ import annotations

import json

import pytest

from swag_bot.interfaces import Message, StreamingLLMClient, Tool, ToolCall
from swag_bot.models.errors import ModelError
from swag_bot.models.http import HTTPResponse
from swag_bot.models.ollama import OllamaClient


class ScriptedTransport:
    """Records calls and returns queued bodies."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._responses: list[tuple[int, object]] = []
        self._streams: list[list[object]] = []

    def push(self, status: int, payload: object) -> None:
        self._responses.append((status, payload))

    def push_stream(self, events: list[object]) -> None:
        self._streams.append(events)

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: object,
        timeout: float,
    ) -> HTTPResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "body": _loads(body),
                "timeout": timeout,
                "stream": False,
            }
        )
        status, payload = self._responses.pop(0)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return HTTPResponse(status, raw)

    def stream(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: object,
        timeout: float,
    ):
        self.calls.append(
            {"method": method, "url": url, "body": _loads(body), "timeout": timeout, "stream": True}
        )
        events = self._streams.pop(0)
        for event in events:
            if isinstance(event, bytes):
                yield event
            else:
                yield (json.dumps(event) + "\n").encode()


def _loads(body: bytes | None) -> object:
    if not body:
        return None
    return json.loads(body)


def _client(transport: ScriptedTransport, model: str = "llama3.2") -> OllamaClient:
    return OllamaClient(model=model, base_url="http://ollama.test", transport=transport)


def test_client_is_a_streaming_llm() -> None:
    client = _client(ScriptedTransport())
    assert isinstance(client, StreamingLLMClient)


def test_chat_and_complete() -> None:
    transport = ScriptedTransport()
    transport.push(
        200,
        {
            "model": "llama3.2",
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
            "done_reason": "stop",
        },
    )
    client = _client(transport)
    assert client.complete("ping") == "ok"
    body = transport.calls[0]["body"]
    assert isinstance(body, dict)
    assert body["model"] == "llama3.2"
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "user"


def test_native_tool_call_normalizes_string_arguments() -> None:
    transport = ScriptedTransport()
    transport.push(
        200,
        {
            "model": "llama3.2",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "add", "arguments": '{"a": 1, "b": 2}'}}
                ],
            },
            "done": True,
            "done_reason": "stop",
        },
    )
    tool = Tool(name="add", description="add")
    response = _client(transport).chat([Message.user("sum")], tools=[tool])
    assert response.message.tool_calls == [
        ToolCall(id=response.message.tool_calls[0].id, name="add", arguments={"a": 1, "b": 2})
    ]
    assert response.message.tool_calls[0].arguments == {"a": 1, "b": 2}
    sent = transport.calls[0]["body"]
    assert isinstance(sent, dict)
    assert sent["tools"][0]["function"]["name"] == "add"


def test_json_fallback_when_native_tools_are_rejected() -> None:
    transport = ScriptedTransport()
    transport.push(400, {"error": "llama3.2 does not support tools"})
    transport.push(
        200,
        {
            "model": "llama3.2",
            "message": {
                "role": "assistant",
                "content": '{"tool_calls":[{"name":"add","arguments":{"a":1}}]}',
            },
            "done": True,
            "done_reason": "stop",
        },
    )
    tool = Tool(name="add", description="add")
    response = _client(transport).chat([Message.user("sum")], tools=[tool])
    assert response.message.tool_calls[0].name == "add"
    assert response.message.tool_calls[0].arguments == {"a": 1}
    assert response.message.content is None
    second = transport.calls[1]["body"]
    assert isinstance(second, dict)
    assert "tools" not in second
    assert second["messages"][0]["role"] == "system"
    assert "tool_calls" in second["messages"][0]["content"]


def test_json_in_text_when_the_model_ignores_native_tools() -> None:
    transport = ScriptedTransport()
    transport.push(
        200,
        {
            "model": "llama3.2",
            "message": {
                "role": "assistant",
                "content": '```json\n{"name":"add","arguments":{"a":4}}\n```',
            },
            "done": True,
        },
    )
    tool = Tool(name="add", description="add")
    response = _client(transport).chat([Message.user("sum")], tools=[tool])
    assert len(transport.calls) == 1
    assert response.message.tool_calls[0].arguments == {"a": 4}


def test_stream_yields_each_ndjson_line() -> None:
    transport = ScriptedTransport()
    transport.push_stream(
        [
            {"message": {"role": "assistant", "content": "Hi"}, "done": False},
            {
                "message": {"role": "assistant", "content": " there"},
                "done": True,
                "done_reason": "stop",
            },
        ]
    )
    chunks = list(_client(transport).stream([Message.user("hi")]))
    assert [chunk.delta for chunk in chunks] == ["Hi", " there"]
    assert chunks[0].finish_reason is None
    assert chunks[1].finish_reason == "stop"
    assert transport.calls[0]["stream"] is True


def test_stream_falls_back_without_buffering_a_single_chunk() -> None:
    transport = ScriptedTransport()
    transport.push_stream([{"error": "model does not support tools"}])
    transport.push_stream(
        [
            {"message": {"content": "{"}, "done": False},
            {"message": {"content": "}"}, "done": True, "done_reason": "stop"},
        ]
    )
    tool = Tool(name="add", description="add")
    chunks = list(_client(transport).stream([Message.user("sum")], tools=[tool]))
    assert [chunk.delta for chunk in chunks] == ["{", "}"]
    assert transport.calls[1]["stream"] is True


def test_list_models_and_unreachable() -> None:
    transport = ScriptedTransport()
    transport.push(200, {"models": [{"name": "llama3.2:latest"}, {"model": "qwen2.5:7b"}]})
    client = _client(transport)
    assert client.list_models() == ["llama3.2:latest", "qwen2.5:7b"]
    assert transport.calls[0]["url"] == "http://ollama.test/api/tags"

    transport.push(500, {"error": "nope"})
    assert client.list_models() is None


def test_http_error_is_a_model_error() -> None:
    transport = ScriptedTransport()
    transport.push(404, {"error": "model not found"})
    with pytest.raises(ModelError, match="model not found"):
        _client(transport).complete("hi")


def test_error_text_redacts_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")
    transport = ScriptedTransport()
    transport.push(500, {"error": "echo sk-test-should-not-leak"})
    with pytest.raises(ModelError) as caught:
        _client(transport).complete("hi")
    assert "sk-test-should-not-leak" not in str(caught.value)
    assert "$OPENAI_API_KEY" in str(caught.value)
