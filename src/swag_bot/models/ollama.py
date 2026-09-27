"""Native Ollama client over the local HTTP API.

Ollama is the free, offline default. No API key is read or sent. The host
comes from ``settings.model.api_base`` when that is set, otherwise from
``OLLAMA_HOST``, otherwise ``http://127.0.0.1:11434``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from swag_bot.interfaces import (
    ChatChunk,
    ChatResponse,
    Message,
    StreamingLLMClient,
    Tool,
)
from swag_bot.models.errors import ModelError, ToolCallingUnsupported
from swag_bot.models.hints import explain_ollama_http
from swag_bot.models.http import HTTPTransport, UrllibTransport
from swag_bot.models.keys import redact_secrets
from swag_bot.models.tools import (
    apply_text_tool_calls,
    json_tool_instruction,
    normalize_tool_calls,
    parse_tool_calls_from_text,
    tools_as_openai,
)

_DEFAULT_HOST = "http://127.0.0.1:11434"
_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/x-ndjson"}


class OllamaClient:
    """``StreamingLLMClient`` for a local Ollama daemon."""

    def __init__(
        self,
        *,
        model: str = "llama3.2",
        base_url: str | None = None,
        timeout: float = 120.0,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.model = model
        self.base_url = _normalize_base(base_url)
        self.timeout = timeout
        self._transport = transport if transport is not None else UrllibTransport()

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ChatResponse:
        """One non-streaming ``/api/chat`` turn. Falls back to JSON tool calls.

        ``response_format`` is an OpenAI-style schema. Ollama receives it as
        ``format``. A model that rejects the schema is asked once more without it.
        """
        chosen = model or self.model
        if tools:
            try:
                return self._chat_once(
                    messages,
                    tools=tools,
                    model=chosen,
                    native_tools=True,
                    response_format=response_format,
                )
            except ToolCallingUnsupported:
                instructed = _with_tool_instruction(messages, tools)
                response = self._chat_once(
                    instructed,
                    tools=None,
                    model=chosen,
                    native_tools=False,
                    response_format=response_format,
                )
                return _overlay_text_tool_calls(response, tools)
        return self._chat_once(
            messages,
            tools=None,
            model=chosen,
            native_tools=False,
            response_format=response_format,
        )

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        """Single user prompt in, assistant text out."""
        response = self.chat([Message.user(prompt)], model=model)
        return response.message.content or ""

    def stream(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> Iterator[ChatChunk]:
        """Yield ``/api/chat`` NDJSON events as they arrive.

        When the daemon rejects native tools, the request is sent again with
        streaming still on and the JSON tool instruction in a system message.
        Tokens are the daemon's deltas, not a buffer split after the fact.
        """
        chosen = model or self.model
        payload_messages = list(messages)
        native = bool(tools)
        if tools:
            try:
                yield from self._stream_once(payload_messages, tools, chosen, native_tools=True)
                return
            except ToolCallingUnsupported:
                payload_messages = _with_tool_instruction(messages, tools)
                native = False
        yield from self._stream_once(payload_messages, tools if native else None, chosen, native)

    def list_models(self, *, timeout: float = 1.0) -> list[str] | None:
        """Model names from ``/api/tags``, or None when the daemon is unreachable."""
        try:
            response = self._transport.request(
                "GET",
                f"{self.base_url}/api/tags",
                None,
                {},
                timeout,
            )
        except ModelError:
            return None
        if response.status >= 400:
            return None
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        names: list[str] = []
        for item in payload.get("models") or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if isinstance(name, str) and name:
                    names.append(name)
        return names

    def _chat_once(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None,
        model: str,
        native_tools: bool,
        response_format: Mapping[str, Any] | None = None,
        _allow_format_retry: bool = True,
    ) -> ChatResponse:
        payload = _chat_payload(
            messages,
            model=model,
            tools=tools if native_tools else None,
            stream=False,
            response_format=response_format,
        )
        response = self._transport.request(
            "POST",
            f"{self.base_url}/api/chat",
            _dump(payload),
            _JSON_HEADERS,
            self.timeout,
        )
        if response.status >= 400:
            detail = redact_secrets(response.text())
            if native_tools and _tools_unsupported(response.status, detail):
                raise ToolCallingUnsupported(detail)
            if (
                response_format is not None
                and _allow_format_retry
                and _format_rejected(response.status, detail)
            ):
                return self._chat_once(
                    messages,
                    tools=tools,
                    model=model,
                    native_tools=native_tools,
                    response_format=None,
                    _allow_format_retry=False,
                )
            raise ModelError(explain_ollama_http(response.status, detail, model))
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise ModelError("ollama returned non-JSON for /api/chat") from exc
        if not isinstance(body, dict):
            raise ModelError("ollama returned an unexpected /api/chat payload")
        return _response_from_body(body, model, tools if native_tools else None)

    def _stream_once(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None,
        model: str,
        native_tools: bool,
    ) -> Iterator[ChatChunk]:
        payload = _chat_payload(
            messages,
            model=model,
            tools=tools if native_tools else None,
            stream=True,
        )
        try:
            lines = self._transport.stream(
                "POST",
                f"{self.base_url}/api/chat",
                _dump(payload),
                _JSON_HEADERS,
                self.timeout,
            )
            for line in lines:
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ModelError("ollama stream returned a non-JSON line") from exc
                if not isinstance(event, dict):
                    continue
                error = event.get("error")
                if isinstance(error, str):
                    detail = redact_secrets(error)
                    if native_tools and _tools_unsupported(400, detail):
                        raise ToolCallingUnsupported(detail)
                    raise ModelError(detail)
                chunk = _chunk_from_event(event)
                if chunk is None:
                    continue
                yield chunk
        except ModelError as exc:
            if native_tools and _tools_unsupported(400, str(exc)):
                raise ToolCallingUnsupported(str(exc)) from exc
            raise


def resolve_ollama_base_url(api_base: str | None = None) -> str:
    """Ollama root URL. ``api_base`` wins, then ``OLLAMA_HOST``, then localhost."""
    return _normalize_base(api_base)


def _normalize_base(base_url: str | None) -> str:
    raw = (base_url or os.environ.get("OLLAMA_HOST") or _DEFAULT_HOST).strip()
    if not raw:
        raw = _DEFAULT_HOST
    return raw.rstrip("/")


def _dump(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _chat_payload(
    messages: Sequence[Message],
    *,
    model: str,
    tools: Sequence[Tool] | None,
    stream: bool,
    response_format: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [_ollama_message(message) for message in messages],
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools_as_openai(tools)
    formatted = _ollama_format(response_format)
    if formatted is not None:
        payload["format"] = formatted
    return payload


def _ollama_format(response_format: Mapping[str, Any] | None) -> Any | None:
    """Translate an OpenAI ``response_format`` into Ollama's ``format`` field."""
    if not response_format:
        return None
    kind = response_format.get("type")
    if kind == "json_object":
        return "json"
    if kind == "json_schema":
        wrapper = response_format.get("json_schema")
        if isinstance(wrapper, Mapping):
            schema = wrapper.get("schema")
            if isinstance(schema, Mapping):
                return dict(schema)
        return "json"
    if kind == "object":
        return dict(response_format)
    return "json"


def _format_rejected(status: int, detail: str) -> bool:
    if status not in {400, 422}:
        return False
    text = detail.lower()
    return any(token in text for token in ("format", "schema", "structured"))


def _ollama_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role.value,
        "content": message.content or "",
    }
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.name:
        payload["name"] = message.name
    return payload


def _response_from_body(
    body: dict[str, Any],
    model: str,
    tools: Sequence[Tool] | None,
) -> ChatResponse:
    message = _as_dict(body.get("message"))
    content = message.get("content")
    text = content if isinstance(content, str) else None
    native = normalize_tool_calls(message.get("tool_calls"))
    if tools and not native:
        allowed = {tool.name for tool in tools}
        native = parse_tool_calls_from_text(text, allowed_names=allowed)
        text = apply_text_tool_calls(text, native)
    finish = body.get("done_reason")
    finish_reason = finish if isinstance(finish, str) else None
    reported = body.get("model")
    return ChatResponse(
        message=Message.assistant(text, native),
        model=reported if isinstance(reported, str) else model,
        finish_reason=finish_reason,
    )


def _chunk_from_event(event: dict[str, Any]) -> ChatChunk | None:
    message = _as_dict(event.get("message"))
    content = message.get("content")
    delta = content if isinstance(content, str) else ""
    tool_calls = normalize_tool_calls(message.get("tool_calls"))
    done = bool(event.get("done"))
    reason = event.get("done_reason")
    finish = reason if isinstance(reason, str) else ("stop" if done else None)
    if not delta and not tool_calls and finish is None:
        return None
    return ChatChunk(
        delta=delta,
        tool_call_deltas=tool_calls,
        finish_reason=finish if done else None,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _tools_unsupported(status: int, detail: str) -> bool:
    if status not in {400, 404, 422, 500}:
        return False
    text = detail.lower()
    needles = (
        "does not support tools",
        "does not support tool",
        "tool calling is not supported",
        "does not support function",
        "unsupported tool",
        "tools are not supported",
    )
    return any(needle in text for needle in needles)


def _with_tool_instruction(messages: Sequence[Message], tools: Sequence[Tool]) -> list[Message]:
    instruction = Message.system(json_tool_instruction(tools))
    return [instruction, *messages]


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


def _protocol_check(client: OllamaClient) -> StreamingLLMClient:
    """Keep the class aligned with the protocol for type checkers."""
    return client
