"""Test doubles for the shared protocols.

Owning agents should use these in unit tests instead of a real model, Docker,
or a prompt. You may add optional behavior that defaults to what is here.
Do not change the existing method names or the success path of ``add``,
``search``, ``get``, ``delete``, ``chat``, ``complete``, ``prompt``,
``read_file``, or ``write_file``.

``FakeSandbox.run`` records the command and does not execute it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from swag_bot.interfaces import (
    ActionRequest,
    ChatResponse,
    CommandResult,
    MemoryItem,
    Message,
    Tool,
    resolve_sandbox_path,
)


class FakeLLMClient:
    """Scripted ``LLMClient``.

    Queue ``ChatResponse`` objects or plain strings (assistant text).
    ``chat`` pops the next item. With an empty queue it returns an empty
    assistant message. ``complete`` is ``chat`` with one user message.
    """

    def __init__(self, responses: Sequence[ChatResponse | str] | None = None) -> None:
        self._queue: list[ChatResponse | str] = list(responses or [])
        self.messages: list[list[Message]] = []
        self.tools: list[Sequence[Tool] | None] = []
        self.models: list[str | None] = []
        self.formats: list[Any] = []

    def push(self, response: ChatResponse | str) -> None:
        """Append one scripted response."""
        self._queue.append(response)

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
        response_format: Any = None,
    ) -> ChatResponse:
        self.messages.append(list(messages))
        self.tools.append(tools)
        self.models.append(model)
        self.formats.append(response_format)
        if not self._queue:
            return ChatResponse(message=Message.assistant(""))
        item = self._queue.pop(0)
        if isinstance(item, str):
            return ChatResponse(message=Message.assistant(item))
        return item

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        response = self.chat([Message.user(prompt)], model=model)
        return response.message.content or ""


class FakeSandbox:
    """In-process workdir. ``run`` does not execute the command.

    File reads and writes are real, and they stay inside ``workdir``.
    Script a ``CommandResult`` with ``script`` when a test needs a specific
    exit code. Otherwise ``run`` returns exit code 0 and empty output.
    """

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir
        self._workdir.mkdir(parents=True, exist_ok=True)
        self.commands: list[str] = []
        self.timeouts: list[float | None] = []
        self._scripted: list[CommandResult] = []

    @property
    def workdir(self) -> Path:
        return self._workdir

    def script(self, result: CommandResult) -> None:
        """Queue a result for the next ``run`` call."""
        self._scripted.append(result)

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        self.commands.append(command)
        self.timeouts.append(timeout)
        if self._scripted:
            result = self._scripted.pop(0)
            if not result.command:
                return result.model_copy(update={"command": command})
            return result
        return CommandResult(command=command, exit_code=0, stdout="", stderr="")

    def read_file(self, path: str) -> str:
        target = resolve_sandbox_path(self._workdir, path)
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        target = resolve_sandbox_path(self._workdir, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class InMemoryMemoryStore:
    """Process-local ``MemoryStore``. Search is a case-insensitive substring.

    Matches look at ``content`` and at each metadata value. Newer items win
    ties. An empty or whitespace query returns nothing.
    """

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        item = MemoryItem(
            id=uuid4().hex,
            content=content,
            metadata=dict(metadata or {}),
            created_at=datetime.now(UTC),
        )
        self._items[item.id] = item
        return item

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        if limit <= 0 or not query.strip():
            return []
        needle = query.casefold()
        matches = [item for item in self._items.values() if needle in _haystack(item)]
        matches.sort(key=lambda item: item.created_at, reverse=True)
        return matches[:limit]

    def get(self, item_id: str) -> MemoryItem | None:
        return self._items.get(item_id)

    def delete(self, item_id: str) -> bool:
        return self._items.pop(item_id, None) is not None


class AutoApprovePrompter:
    """``ApprovalPrompter`` that always allows and records what it was shown."""

    def __init__(self) -> None:
        self.prompts: list[ActionRequest] = []

    def prompt(self, action: ActionRequest) -> bool:
        self.prompts.append(action)
        return True


def _haystack(item: MemoryItem) -> str:
    parts = [item.content]
    parts.extend(str(value) for value in item.metadata.values())
    return "\n".join(parts).casefold()
