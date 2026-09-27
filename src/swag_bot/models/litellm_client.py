"""LiteLLM client for OpenAI, Anthropic, Gemini, and OpenRouter.

LiteLLM is an optional extra (``pip install -e ".[models]"``, which installs
the ``litellm`` package). Keys are read from the environment at request time
and passed only as the ``api_key`` argument. They are never stored on the
instance in a way that ``repr`` would show, and errors are redacted.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, cast

from pydantic import ValidationError

from swag_bot.interfaces import (
    ChatChunk,
    ChatResponse,
    Message,
    StreamingLLMClient,
    Tool,
    ToolCall,
)
from swag_bot.models.errors import ModelError, ToolCallingUnsupported
from swag_bot.models.keys import provider_api_key, redact_secrets
from swag_bot.models.tools import (
    apply_text_tool_calls,
    json_tool_instruction,
    normalize_tool_calls,
    parse_tool_calls_from_text,
    tools_as_openai,
)

CompletionFn = Callable[..., Any]

_INSTALL_HINT = (
    'LiteLLM is not installed. Install the optional extra: pip install -e ".[models]"'
)

_PREFIX = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "openrouter": "openrouter",
}


class LiteLLMClient:
    """``StreamingLLMClient`` that routes through LiteLLM.

    ``completion_fn`` replaces ``litellm.completion`` in tests so CI does not
    import LiteLLM or open a socket.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_base: str | None = None,
        timeout: float = 120.0,
        completion_fn: CompletionFn | None = None,
    ) -> None:
        self.provider = provider.strip().lower()
        self.model = model
        self.api_base = api_base
        self.timeout = timeout
        self._completion_fn = completion_fn

    def __repr__(self) -> str:
        return f"LiteLLMClient(provider={self.provider!r}, model={self.model!r})"

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        """One completion. Native tools first, then JSON-in-text if needed."""
        chosen = model or self.model
        if tools:
            try:
                return self._complete(
                    messages,
                    tools=tools,
                    model=chosen,
                    native_tools=True,
                    stream=False,
                )
            except ToolCallingUnsupported:
                instructed = _with_tool_instruction(messages, tools)
                response = self._complete(
                    instructed, tools=None, model=chosen, native_tools=False, stream=False
                )
                return _overlay_text_tool_calls(response, tools)
        return self._complete(messages, tools=None, model=chosen, native_tools=False, stream=False)

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        """Single user prompt in, assistant text out."""
        response = self.chat([Message.user(prompt)], model=model)
        return response.message.content or ""

    def complete_structured(
        self,
        messages: Sequence[Message],
        schema: Mapping[str, Any],
        *,
        model: str | None = None,
    ) -> ChatResponse:
        """One completion with a JSON-schema ``response_format``.

        Providers that reject the schema raise ``ModelError``. The harness
        retries without the schema when the error is about the format.
        """
        chosen = model or self.model
        return self._complete(
            messages,
            tools=None,
            model=chosen,
            native_tools=False,
            stream=False,
            response_schema=schema,
        )

    def stream(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> Iterator[ChatChunk]:
        """Yield provider stream chunks. Does not buffer the full turn first."""
        chosen = model or self.model
        payload_messages: Sequence[Message] = messages
        use_tools = tools
        if tools:
            try:
                yield from self._stream_once(messages, tools, chosen)
                return
            except ToolCallingUnsupported:
                payload_messages = _with_tool_instruction(messages, tools)
                use_tools = None
        yield from self._stream_once(payload_messages, use_tools, chosen)

    def litellm_model(self, model: str | None = None) -> str:
        """Model string LiteLLM expects, including the provider prefix."""
        chosen = model or self.model
        if self.provider == "litellm":
            return chosen
        prefix = _PREFIX.get(self.provider)
        if prefix is None:
            return chosen
        if chosen.startswith(prefix + "/"):
            return chosen
        return f"{prefix}/{chosen}"

    def _complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None,
        model: str,
        native_tools: bool,
        stream: bool,
        response_schema: Mapping[str, Any] | None = None,
    ) -> ChatResponse:
        raw = self._invoke(
            messages,
            tools if native_tools else None,
            model,
            stream=stream,
            response_schema=response_schema,
        )
        reported_tools = tools if native_tools else None
        return _response_from_litellm(raw, self.litellm_model(model), reported_tools)

    def _stream_once(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None,
        model: str,
    ) -> Iterator[ChatChunk]:
        raw = self._invoke(messages, tools, model, stream=True)
        if isinstance(raw, ChatResponse):
            raise ModelError(
                "streaming completion returned a full response; refusing to fake a stream"
            )
        try:
            iterator = iter(raw)
        except TypeError as exc:
            raise ModelError("LiteLLM streaming did not return an iterator") from exc
        for chunk in iterator:
            yield _chunk_from_litellm(chunk)

    def _invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None,
        model: str,
        *,
        stream: bool,
        response_schema: Mapping[str, Any] | None = None,
    ) -> Any:
        fn = self._completion_fn or _load_litellm_completion()
        kwargs: dict[str, Any] = {
            "model": self.litellm_model(model),
            "messages": [_openai_message(message) for message in messages],
            "stream": stream,
            "timeout": self.timeout,
        }
        if tools:
            kwargs["tools"] = tools_as_openai(tools)
            kwargs["tool_choice"] = "auto"
        elif response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "swag_structured",
                    "schema": dict(response_schema),
                },
            }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        # Read the key at call time. Do not store it on self.
        api_key = provider_api_key(self.provider)
        if api_key:
            kwargs["api_key"] = api_key
        try:
            return fn(**kwargs)
        except ToolCallingUnsupported:
            raise
        except Exception as exc:
            message = redact_secrets(str(exc))
            if tools and _tools_unsupported(message):
                raise ToolCallingUnsupported(message) from exc
            raise ModelError(message) from exc


def _load_litellm_completion() -> CompletionFn:
    try:
        litellm = importlib.import_module("litellm")
    except ImportError as exc:
        raise ModelError(_INSTALL_HINT) from exc
    completion = getattr(litellm, "completion", None)
    if completion is None:
        raise ModelError(_INSTALL_HINT)
    # importlib + getattr is Any. The callable is the LiteLLM completion function.
    return cast(CompletionFn, completion)


def _openai_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.name:
        payload["name"] = message.name
    return payload


def _response_from_litellm(
    raw: Any,
    model: str,
    tools: Sequence[Tool] | None,
) -> ChatResponse:
    message, finish, reported = _choice_message(raw)
    content = _field(message, "content")
    text = content if isinstance(content, str) else None
    native = normalize_tool_calls(_field(message, "tool_calls"))
    if tools and not native:
        allowed = {tool.name for tool in tools}
        native = parse_tool_calls_from_text(text, allowed_names=allowed)
        text = apply_text_tool_calls(text, native)
    return ChatResponse(
        message=Message.assistant(text, native),
        model=reported or model,
        finish_reason=finish,
    )


def _chunk_from_litellm(raw: Any) -> ChatChunk:
    choice = _first_choice(raw)
    delta = _field(choice, "delta") or {}
    content = _field(delta, "content")
    text = content if isinstance(content, str) else ""
    finish = _field(choice, "finish_reason")
    finish_reason = finish if isinstance(finish, str) else None
    # Only emit a tool-call delta once arguments are a dict or valid JSON.
    # Partial argument strings stay on the provider chunk and are not invented.
    tool_deltas = _complete_stream_tool_calls(_field(delta, "tool_calls"))
    return ChatChunk(delta=text, tool_call_deltas=tool_deltas, finish_reason=finish_reason)


def _complete_stream_tool_calls(raw: Any) -> list[ToolCall]:
    if not raw:
        return []
    ready: list[Any] = []
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        data_arguments = _tool_arguments(item)
        if isinstance(data_arguments, str):
            stripped = data_arguments.strip()
            if not stripped:
                continue
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                continue
        ready.append(item)
    try:
        return normalize_tool_calls(ready)
    except (ValueError, ValidationError):
        return []


def _tool_arguments(item: Any) -> Any:
    function = _field(item, "function")
    if function is None:
        return _field(item, "arguments")
    return _field(function, "arguments")


def _choice_message(raw: Any) -> tuple[Any, str | None, str | None]:
    choice = _first_choice(raw)
    message = _field(choice, "message")
    finish = _field(choice, "finish_reason")
    reported = _field(raw, "model")
    finish_reason = finish if isinstance(finish, str) else None
    model = reported if isinstance(reported, str) else None
    return message, finish_reason, model


def _first_choice(raw: Any) -> Any:
    choices = _field(raw, "choices")
    if not choices:
        raise ModelError("LiteLLM response did not include choices")
    return choices[0]


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _tools_unsupported(message: str) -> bool:
    text = message.lower()
    needles = (
        "does not support tools",
        "does not support tool",
        "tool calling is not supported",
        "does not support function",
        "unsupported tool",
        "tools are not supported",
        "function calling is not enabled",
        "no tools",
    )
    return any(needle in text for needle in needles)


def _with_tool_instruction(messages: Sequence[Message], tools: Sequence[Tool]) -> list[Message]:
    return [Message.system(json_tool_instruction(tools)), *messages]


def _overlay_text_tool_calls(response: ChatResponse, tools: Sequence[Tool]) -> ChatResponse:
    if response.message.tool_calls:
        return response
    allowed = {tool.name for tool in tools}
    calls = parse_tool_calls_from_text(response.message.content, allowed_names=allowed)
    if not calls:
        return response
    content = apply_text_tool_calls(response.message.content, calls)
    return ChatResponse(
        message=Message.assistant(content, calls),
        model=response.model,
        finish_reason=response.finish_reason,
    )


def _protocol_check(client: LiteLLMClient) -> StreamingLLMClient:
    return client
