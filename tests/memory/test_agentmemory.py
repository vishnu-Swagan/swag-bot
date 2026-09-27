"""agentmemory HTTP adapter. The transport is scripted; nothing listens on a port."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from swag_bot.config import MemorySettings, Settings
from swag_bot.memory.agentmemory import AgentMemoryStore, agentmemory_from_settings
from swag_bot.memory.errors import MemoryError
from swag_bot.memory.http import HTTPResponse


class ScriptedHTTP:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._responses: list[tuple[int, object]] = []

    def push(self, status: int, payload: object) -> None:
        self._responses.append((status, payload))

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "body": json.loads(body) if body else None,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        status, payload = self._responses.pop(0)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return HTTPResponse(status, raw)


def test_rest_add_search_get_delete() -> None:
    http = ScriptedHTTP()
    http.push(201, {"id": "m1", "content": "chose JWT refresh rotation"})
    http.push(
        200,
        {
            "results": [
                {
                    "id": "m1",
                    "content": "chose JWT refresh rotation",
                    "created_at": "2026-09-27T00:00:00+00:00",
                    "concepts": ["jwt"],
                }
            ]
        },
    )
    http.push(200, {"id": "m1", "content": "chose JWT refresh rotation"})
    http.push(404, {"error": "missing"})
    http.push(200, {"deleted": True})
    http.push(404, {"error": "missing"})
    store = AgentMemoryStore(
        "http://memory.test:3111",
        transport_name="rest",
        secret="test-agentmemory-secret",
        transport=http,
    )
    assert "test-agentmemory-secret" not in repr(store)
    item = store.add("chose JWT refresh rotation", metadata={"tags": ["jwt"]})
    assert item.id == "m1"
    saved = http.calls[0]
    assert saved["method"] == "POST"
    assert saved["url"] == "http://memory.test:3111/agentmemory/remember"
    assert saved["body"] == {
        "content": "chose JWT refresh rotation",
        "type": "fact",
        "concepts": ["jwt"],
    }
    headers = saved["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer test-agentmemory-secret"

    found = store.search("jwt")
    assert found[0].id == "m1"
    assert found[0].content.startswith("chose JWT")
    assert store.search("   ") == []
    assert len(http.calls) == 2

    assert store.get("m1") is not None
    assert store.get("missing") is None
    assert store.delete("m1") is True
    forget = http.calls[4]
    assert forget["url"] == "http://memory.test:3111/agentmemory/forget"
    assert store.delete("missing") is False


def test_mcp_tool_calls() -> None:
    http = ScriptedHTTP()
    http.push(
        200,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps({"id": "m2", "content": "note"})}
                ]
            },
        },
    )
    http.push(
        200,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "results": [
                                    {
                                        "id": "m2",
                                        "content": "note",
                                        "metadata": {"tags": ["a"]},
                                    }
                                ]
                            }
                        ),
                    }
                ]
            },
        },
    )
    store = AgentMemoryStore("http://memory.test:3111", transport_name="mcp", transport=http)
    item = store.add("note", metadata={"tags": ["a"]})
    assert item.id == "m2"
    call = http.calls[0]
    assert call["url"] == "http://memory.test:3111/mcp"
    body = call["body"]
    assert isinstance(body, dict)
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "memory_save"
    found = store.search("note")
    assert found[0].id == "m2"
    assert found[0].metadata["tags"] == ["a"]


def test_mcp_url_is_not_doubled() -> None:
    http = ScriptedHTTP()
    http.push(
        200,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "{}"}]},
        },
    )
    store = AgentMemoryStore("http://memory.test/mcp", transport_name="mcp", transport=http)
    store.add("note")
    assert http.calls[0]["url"] == "http://memory.test/mcp"


def test_from_settings_uses_url_and_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_SECRET", "test-agentmemory-secret")
    monkeypatch.setenv("AGENTMEMORY_TRANSPORT", "mcp")
    settings = Settings(memory=MemorySettings(backend="agentmemory", path="http://memory.test:3111"))
    store = agentmemory_from_settings(settings)
    assert isinstance(store, AgentMemoryStore)
    assert store.base_url == "http://memory.test:3111"
    assert store.transport_name == "mcp"
    assert "test-agentmemory-secret" not in repr(store)

    monkeypatch.delenv("AGENTMEMORY_TRANSPORT")
    inferred = agentmemory_from_settings(
        Settings(memory=MemorySettings(backend="agentmemory", path="http://memory.test/mcp"))
    )
    assert isinstance(inferred, AgentMemoryStore)
    assert inferred.transport_name == "mcp"


def test_http_failure_redacts_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_SECRET", "test-agentmemory-secret")
    http = ScriptedHTTP()
    http.push(500, {"error": "leaked test-agentmemory-secret"})
    store = AgentMemoryStore(
        "http://memory.test",
        secret="test-agentmemory-secret",
        transport=http,
    )
    with pytest.raises(MemoryError) as caught:
        store.add("note")
    assert "test-agentmemory-secret" not in str(caught.value)
    assert "$AGENTMEMORY_SECRET" in str(caught.value)
