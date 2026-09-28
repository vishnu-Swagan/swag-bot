"""LiteLLM client with an injected completion function. No network and no litellm import."""

from __future__ import annotations

import pytest

from swag_bot.interfaces import Message, StreamingLLMClient, Tool
from swag_bot.models.errors import ModelError
from swag_bot.models.litellm_client import LiteLLMClient


class Recorder:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("no scripted response")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _chat(
    content: str,
    tool_calls: list[object] | None = None,
    finish: str = "stop",
) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "model": "openai/gpt-4o-mini",
        "choices": [{"message": message, "finish_reason": finish}],
    }


def test_is_streaming_and_hides_keys_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=Recorder([]))
    assert isinstance(client, StreamingLLMClient)
    assert "sk-test-openai" not in repr(client)


def test_complete_structured_sends_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    recorder = Recorder([_chat('{"ok": true}')])
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=recorder)
    schema = {"type": "object", "required": ["ok"]}
    response = client.complete_structured([Message.user("probe")], schema)
    assert response.message.content == '{"ok": true}'
    call = recorder.calls[0]
    assert call["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "swag_structured", "schema": schema},
    }
    assert "tools" not in call


def test_passes_prefixed_model_and_key_without_storing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    recorder = Recorder([_chat("ok")])
    client = LiteLLMClient(
        provider="anthropic",
        model="claude-3-5-sonnet",
        api_base="https://example.test/v1",
        completion_fn=recorder,
    )
    assert client.complete("hi") == "ok"
    call = recorder.calls[0]
    assert call["model"] == "anthropic/claude-3-5-sonnet"
    assert call["api_key"] == "sk-ant-test"
    assert call["api_base"] == "https://example.test/v1"
    assert call["stream"] is False
    assert "sk-ant-test" not in repr(client)


def test_local_openai_route_sends_a_placeholder_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    recorder = Recorder([_chat("ok")])
    client = LiteLLMClient(
        provider="litellm",
        model="openai/qwen2.5-7b",
        api_base="http://localhost:1234/v1",
        completion_fn=recorder,
    )
    assert client.complete("hi") == "ok"
    call = recorder.calls[0]
    assert call["model"] == "openai/qwen2.5-7b"
    assert call["api_base"] == "http://localhost:1234/v1"
    assert call["api_key"] == "local"


def test_litellm_cloud_prefix_does_not_invent_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    recorder = Recorder([_chat("ok")])
    client = LiteLLMClient(
        provider="litellm",
        model="groq/llama-3.3-70b-versatile",
        completion_fn=recorder,
    )
    assert client.complete("hi") == "ok"
    assert "api_key" not in recorder.calls[0]


def test_provider_prefixes() -> None:
    cases = {
        "openai": "openai/gpt-4o-mini",
        "gemini": "gemini/gemini-2.0-flash",
        "openrouter": "openrouter/anthropic/claude-3.5-sonnet",
    }
    for provider, expected in cases.items():
        model = expected.split("/", 1)[1]
        client = LiteLLMClient(provider=provider, model=model, completion_fn=Recorder([]))
        assert client.litellm_model() == expected
    passthrough = LiteLLMClient(
        provider="litellm",
        model="openai/gpt-4o-mini",
        completion_fn=Recorder([]),
    )
    assert passthrough.litellm_model() == "openai/gpt-4o-mini"
    already = LiteLLMClient(
        provider="openai",
        model="openai/gpt-4o-mini",
        completion_fn=Recorder([]),
    )
    assert already.litellm_model() == "openai/gpt-4o-mini"


def test_native_tool_call_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    recorder = Recorder(
        [
            _chat(
                "",
                tool_calls=[
                    {
                        "id": "call_9",
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"a": 2, "b": 3}'},
                    }
                ],
            )
        ]
    )
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=recorder)
    tool = Tool(name="add", description="add")
    response = client.chat([Message.user("sum")], tools=[tool])
    assert response.message.tool_calls[0].id == "call_9"
    assert response.message.tool_calls[0].arguments == {"a": 2, "b": 3}
    assert recorder.calls[0]["tool_choice"] == "auto"


def test_json_fallback_after_unsupported_tools() -> None:
    recorder = Recorder(
        [
            RuntimeError("this model does not support tools"),
            _chat('{"tool_calls":[{"name":"add","arguments":{"a":1}}]}'),
        ]
    )
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=recorder)
    response = client.chat([Message.user("sum")], tools=[Tool(name="add", description="add")])
    assert response.message.tool_calls[0].arguments == {"a": 1}
    assert "tools" not in recorder.calls[1]
    messages = recorder.calls[1]["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"


def test_exception_text_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")
    recorder = Recorder([RuntimeError("bad key sk-test-should-not-leak")])
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=recorder)
    with pytest.raises(ModelError) as caught:
        client.complete("hi")
    assert "sk-test-should-not-leak" not in str(caught.value)
    assert "$OPENAI_API_KEY" in str(caught.value)


def test_stream_yields_provider_chunks() -> None:
    class Chunk:
        def __init__(self, content: str, finish: str | None) -> None:
            self.choices = [self.Choice(content, finish)]

        class Choice:
            def __init__(self, content: str, finish: str | None) -> None:
                self.delta = self.Delta(content)
                self.finish_reason = finish

            class Delta:
                def __init__(self, content: str) -> None:
                    self.content = content
                    self.tool_calls = None

    recorder = Recorder([[Chunk("hel", None), Chunk("lo", "stop")]])
    client = LiteLLMClient(provider="gemini", model="gemini-2.0-flash", completion_fn=recorder)
    chunks = list(client.stream([Message.user("hi")]))
    assert [chunk.delta for chunk in chunks] == ["hel", "lo"]
    assert chunks[-1].finish_reason == "stop"
    assert recorder.calls[0]["stream"] is True
    assert recorder.calls[0]["model"] == "gemini/gemini-2.0-flash"


def test_partial_tool_argument_is_not_emitted_until_it_is_json() -> None:
    class Chunk:
        def __init__(self, arguments: str | None, finish: str | None = None) -> None:
            self.choices = [self.Choice(arguments, finish)]

        class Choice:
            def __init__(self, arguments: str | None, finish: str | None) -> None:
                self.finish_reason = finish
                self.delta = self.Delta(arguments)

            class Delta:
                def __init__(self, arguments: str | None) -> None:
                    self.content = ""
                    self.tool_calls = [self.Call(arguments)] if arguments is not None else None

                class Call:
                    def __init__(self, arguments: str) -> None:
                        self.id = "call_1"
                        self.function = self.Function(arguments)

                    class Function:
                        def __init__(self, arguments: str) -> None:
                            self.name = "add"
                            self.arguments = arguments

    recorder = Recorder([[Chunk('{"a":'), Chunk('{"a": 1}', "stop")]])
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=recorder)
    chunks = list(client.stream([Message.user("sum")], tools=[Tool(name="add")]))
    assert chunks[0].tool_call_deltas == []
    assert chunks[1].tool_call_deltas[0].arguments == {"a": 1}


def test_response_format_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    schema = {
        "type": "json_schema",
        "json_schema": {"name": "task_plan", "schema": {"type": "object"}},
    }
    recorder = Recorder([_chat("{}")])
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=recorder)
    assert client.chat([Message.user("plan")], response_format=schema).message.content == "{}"
    assert recorder.calls[0]["response_format"] == schema


def test_rejected_response_format_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    recorder = Recorder([RuntimeError("response_format is not supported"), _chat("ok")])
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini", completion_fn=recorder)
    text = client.chat(
        [Message.user("plan")],
        response_format={"type": "json_object"},
    )
    assert text.message.content == "ok"
    assert "response_format" in recorder.calls[0]
    assert "response_format" not in recorder.calls[1]


def test_missing_litellm_package(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __import__

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name == "litellm":
            raise ImportError("no litellm")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded)
    client = LiteLLMClient(provider="openai", model="gpt-4o-mini")
    with pytest.raises(ModelError, match="not installed"):
        client.complete("hi")


def test_openai_call_sends_temperature_and_not_num_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    recorder = Recorder([_chat("ok")])
    client = LiteLLMClient(
        provider="openai",
        model="gpt-4o-mini",
        completion_fn=recorder,
        temperature=0.2,
        num_ctx=32768,
        num_predict=4096,
    )
    assert client.complete("hi") == "ok"
    call = recorder.calls[0]
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 4096
    assert "num_ctx" not in call


def test_ollama_route_sends_num_ctx_and_retries_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    recorder = Recorder(
        [TimeoutError("request to http://127.0.0.1:11434/api/chat timed out"), _chat("ok")]
    )
    client = LiteLLMClient(
        provider="ollama",
        model="qwen2.5:7b",
        completion_fn=recorder,
        num_ctx=32768,
        temperature=0.2,
    )
    assert client.complete("hi") == "ok"
    assert len(recorder.calls) == 2
    assert recorder.calls[0]["num_ctx"] == 32768
    assert recorder.calls[0]["temperature"] == 0.2
    assert recorder.calls[0]["max_tokens"] == 1024
    assert recorder.calls[1]["max_tokens"] == 512
    retry_messages = recorder.calls[1]["messages"]
    assert isinstance(retry_messages, list)
    assert retry_messages[-1]["content"].startswith("Be concise.")
