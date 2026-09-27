"""Call an LLM with a JSON schema when that client implements it.

``LLMClient.chat`` stays unchanged so other branches and test fakes keep
working. Ollama and LiteLLM add ``complete_structured``. Clients without
that method are called with ``chat``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from swag_bot.interfaces import ChatResponse, LLMClient, Message, Tool

_SCHEMA_HINTS = ("format", "schema", "response_format", "structured", "json_schema")


def chat_structured(
    llm: LLMClient,
    messages: Sequence[Message],
    *,
    tools: Sequence[Tool] | None = None,
    model: str | None = None,
    response_schema: Mapping[str, Any] | None = None,
) -> ChatResponse:
    """Chat, using a JSON schema when the client supports ``complete_structured``.

    A provider that rejects the schema is retried once without it. Other
    errors propagate.
    """
    if response_schema is not None and not tools:
        method = getattr(llm, "complete_structured", None)
        if callable(method):
            try:
                response = method(messages, response_schema, model=model)
            except Exception as exc:
                if not schema_rejected(exc):
                    raise
            else:
                if isinstance(response, ChatResponse):
                    return response
    return llm.chat(messages, tools=tools, model=model)


def schema_rejected(exc: BaseException) -> bool:
    """True when ``exc`` looks like a structured-output rejection, not an outage."""
    text = str(exc).lower()
    return any(hint in text for hint in _SCHEMA_HINTS)
