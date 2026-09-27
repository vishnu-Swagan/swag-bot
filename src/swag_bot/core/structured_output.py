"""Ask a model for a plan as JSON when the client supports a response schema.

Ollama accepts a JSON schema on ``format``. LiteLLM accepts OpenAI-style
``response_format``. Clients that do not take the keyword are called normally,
so a test double keeps working.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from swag_bot.interfaces import ChatResponse, LLMClient, Message, Tool

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
                    "success_criteria": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title"],
            },
        }
    },
    "required": ["steps"],
}

# OpenAI / LiteLLM shape. Ollama clients translate this into ``format``.
PLAN_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "task_plan",
        "strict": True,
        "schema": PLAN_SCHEMA,
    },
}


def accepts_response_format(chat: Callable[..., Any]) -> bool:
    """True when ``chat`` has a ``response_format`` parameter or ``**kwargs``."""
    try:
        params = inspect.signature(chat).parameters
    except (TypeError, ValueError):
        return False
    if "response_format" in params:
        return True
    return any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values())


def forward_chat(
    llm: LLMClient,
    messages: Sequence[Message],
    *,
    tools: Sequence[Tool] | None = None,
    model: str | None = None,
    response_format: Mapping[str, Any] | None = None,
) -> ChatResponse:
    """Call ``llm.chat``, passing ``response_format`` only if that client accepts it."""
    if response_format is not None and accepts_response_format(llm.chat):
        extended = cast(Callable[..., ChatResponse], llm.chat)
        return extended(
            messages,
            tools=tools,
            model=model,
            response_format=dict(response_format),
        )
    return llm.chat(messages, tools=tools, model=model)
