"""agentmemory backend (https://github.com/rohitg00/agentmemory).

The server stays outside this process. Swag Bot talks to it over HTTP:

- ``rest`` (default) uses the agentmemory REST API under ``/agentmemory/``.
- ``mcp`` posts JSON-RPC ``tools/call`` requests at the MCP endpoint.

Select the mode with ``AGENTMEMORY_TRANSPORT`` (``rest`` or ``mcp``). The URL
comes from ``settings.memory.path`` when that value is an ``http(s)`` URL,
otherwise from ``AGENTMEMORY_URL``, otherwise ``http://127.0.0.1:3111``.
When ``AGENTMEMORY_SECRET`` is set it is sent as a bearer token and never
written to config or to error text.

This adapter does not import the MCP SDK or the ``swag_bot.mcp`` package.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from swag_bot.config import Settings
from swag_bot.interfaces import MemoryItem
from swag_bot.memory.errors import MemoryError
from swag_bot.memory.http import HTTPResponse, HTTPTransport, UrllibTransport
from swag_bot.memory.util import parse_timestamp, redact_secrets, tags_from_metadata

_DEFAULT_URL = "http://127.0.0.1:3111"
_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class AgentMemoryStore:
    """``MemoryStore`` that proxies to a running agentmemory server."""

    def __init__(
        self,
        base_url: str = _DEFAULT_URL,
        *,
        transport_name: str = "rest",
        secret: str | None = None,
        timeout: float = 30.0,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport_name = transport_name.strip().lower()
        if self.transport_name not in {"rest", "mcp"}:
            raise MemoryError("agentmemory transport must be 'rest' or 'mcp'")
        self._secret = secret if secret else None
        self.timeout = timeout
        self._http = transport if transport is not None else UrllibTransport()
        self._rpc_id = 0

    def __repr__(self) -> str:
        return (
            f"AgentMemoryStore(base_url={self.base_url!r}, transport={self.transport_name!r})"
        )

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        """Save ``content``. Tags in metadata are sent as agentmemory concepts."""
        meta = dict(metadata or {})
        concepts = tags_from_metadata(meta)
        if self.transport_name == "mcp":
            arguments: dict[str, Any] = {"content": content, "type": "fact"}
            if concepts:
                arguments["concepts"] = concepts
            payload = self._mcp("memory_save", arguments)
        else:
            body: dict[str, Any] = {"content": content, "type": "fact"}
            if concepts:
                body["concepts"] = concepts
            payload = self._rest("POST", "/agentmemory/remember", body, ok=(200, 201))
        items = items_from_payload(payload)
        if items:
            item = items[0]
            merged = {**meta, **item.metadata}
            if not item.content:
                item = item.model_copy(update={"content": content, "metadata": merged})
            elif meta:
                item = item.model_copy(update={"metadata": merged})
            return item
        found_id = _extract_id(payload) or uuid4().hex
        return MemoryItem(id=found_id, content=content, metadata=meta, created_at=datetime.now(UTC))

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        """Best-first search. An empty query returns nothing and does not call out."""
        if limit <= 0 or not query.strip():
            return []
        if self.transport_name == "mcp":
            payload = self._mcp("memory_smart_search", {"query": query, "limit": limit})
        else:
            payload = self._rest(
                "POST",
                "/agentmemory/smart-search",
                {"query": query, "limit": limit},
            )
        return items_from_payload(payload)[:limit]

    def get(self, item_id: str) -> MemoryItem | None:
        """Fetch one memory. Missing ids return None."""
        if self.transport_name == "mcp":
            payload = self._mcp("memory_recall", {"query": item_id, "limit": 5})
            for item in items_from_payload(payload):
                if item.id == item_id:
                    return item
            return None
        try:
            payload = self._rest("GET", f"/agentmemory/memories/{item_id}", None)
        except MemoryError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        items = items_from_payload(payload)
        for item in items:
            if item.id == item_id:
                return item
        if items:
            return items[0]
        found = _extract_id(payload)
        if found == item_id and isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, str):
                return MemoryItem(id=found, content=content, metadata={})
        return None

    def delete(self, item_id: str) -> bool:
        """Forget one memory. Return True only when the server deleted it."""
        if self.transport_name == "mcp":
            try:
                payload = self._mcp("memory_governance_delete", {"id": item_id})
            except MemoryError as exc:
                if "HTTP 404" in str(exc) or "not found" in str(exc).lower():
                    return False
                raise
            return _deleted_flag(payload)
        try:
            payload = self._rest(
                "POST",
                "/agentmemory/forget",
                {"id": item_id, "memoryId": item_id},
            )
        except MemoryError as exc:
            if "HTTP 404" in str(exc):
                return False
            raise
        return _deleted_flag(payload)

    def list_recent(self, *, limit: int = 20) -> list[MemoryItem]:
        """Recent memories. REST uses ``GET /agentmemory/memories``."""
        if limit <= 0:
            return []
        if self.transport_name == "mcp":
            payload = self._mcp("memory_smart_search", {"query": "*", "limit": limit})
        else:
            payload = self._rest("GET", f"/agentmemory/memories?limit={limit}", None)
        return items_from_payload(payload)[:limit]

    def _rest(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        ok: tuple[int, ...] = (200,),
    ) -> Any:
        url = self.base_url + path
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        response = self._send(method, url, raw)
        allowed = set(ok)
        if 200 in allowed:
            allowed.add(201)
        if response.status == 404:
            raise MemoryError(f"agentmemory HTTP 404 for {path}")
        if response.status not in allowed:
            detail = redact_secrets(_body_text(response))
            raise MemoryError(f"agentmemory HTTP {response.status} for {path}: {detail}")
        return _decode_body(response)

    def _mcp(self, name: str, arguments: dict[str, Any]) -> Any:
        self._rpc_id += 1
        envelope = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = self._send("POST", _mcp_url(self.base_url), json.dumps(envelope).encode("utf-8"))
        if response.status == 404:
            raise MemoryError(f"agentmemory HTTP 404 for {name}")
        if response.status >= 400:
            detail = redact_secrets(_body_text(response))
            raise MemoryError(f"agentmemory HTTP {response.status} for {name}: {detail}")
        payload = _decode_body(response)
        if isinstance(payload, dict) and payload.get("error"):
            detail = redact_secrets(json.dumps(payload["error"]))
            raise MemoryError(f"agentmemory MCP error for {name}: {detail}")
        result = payload.get("result") if isinstance(payload, dict) else payload
        if isinstance(result, dict) and result.get("isError"):
            detail = redact_secrets(json.dumps(result))
            lowered = detail.lower()
            if "not found" in lowered:
                raise MemoryError(f"agentmemory HTTP 404 for {name}: {detail}")
            raise MemoryError(f"agentmemory MCP error for {name}: {detail}")
        return _unwrap_mcp_result(result)

    def _send(self, method: str, url: str, body: bytes | None) -> HTTPResponse:
        headers = dict(_JSON_HEADERS)
        if self._secret:
            headers["Authorization"] = f"Bearer {self._secret}"
        return self._http.request(method, url, body, headers, self.timeout)


def agentmemory_from_settings(settings: Settings) -> AgentMemoryStore:
    """Build a store from settings and the agentmemory environment variables."""
    configured = (settings.memory.path or "").strip()
    if configured.startswith(("http://", "https://")):
        base = configured
    else:
        base = os.environ.get("AGENTMEMORY_URL", "").strip() or _DEFAULT_URL
    transport = os.environ.get("AGENTMEMORY_TRANSPORT", "").strip().lower()
    if transport not in {"rest", "mcp"}:
        transport = "mcp" if base.rstrip("/").endswith("/mcp") else "rest"
    secret = os.environ.get("AGENTMEMORY_SECRET", "").strip() or None
    return AgentMemoryStore(base, transport_name=transport, secret=secret)


def items_from_payload(payload: Any) -> list[MemoryItem]:
    """Normalize the different list shapes agentmemory and MCP return."""
    data = _unwrap_mcp_result(payload)
    records = _record_list(data)
    items: list[MemoryItem] = []
    for record in records:
        item = _item_from_record(record)
        if item is not None:
            items.append(item)
    return items


def _record_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "memories", "observations", "items", "matches", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        if _extract_content(data) is not None or _extract_id(data) is not None:
            return [data]
    return []


def _item_from_record(record: Any) -> MemoryItem | None:
    if isinstance(record, str):
        return MemoryItem(id=uuid4().hex, content=record, metadata={})
    if not isinstance(record, dict):
        return None
    content = _extract_content(record)
    item_id = _extract_id(record) or uuid4().hex
    if content is None:
        return None
    metadata = _as_dict(record.get("metadata"))
    concepts = record.get("concepts")
    if concepts and "tags" not in metadata and "concepts" not in metadata:
        metadata = {**metadata, "concepts": concepts}
    created = (
        parse_timestamp(record.get("created_at"))
        or parse_timestamp(record.get("createdAt"))
        or parse_timestamp(record.get("timestamp"))
        or datetime.now(UTC)
    )
    return MemoryItem(id=item_id, content=content, metadata=metadata, created_at=created)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _extract_content(record: dict[str, Any]) -> str | None:
    for key in ("content", "text", "observation", "summary", "document", "page_content"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None


def _extract_id(payload: Any, depth: int = 0) -> str | None:
    if depth > 3 or not isinstance(payload, dict):
        return None
    for key in ("id", "memory_id", "memoryId", "uuid"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("memory", "observation", "result", "item"):
        found = _extract_id(payload.get(key), depth + 1)
        if found:
            return found
    return None


def _unwrap_mcp_result(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("content"), list):
        texts: list[str] = []
        for part in payload["content"]:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif isinstance(part, str):
                texts.append(part)
        if len(texts) == 1:
            parsed = _maybe_json(texts[0])
            return parsed
        if texts:
            parsed_many = [_maybe_json(text) for text in texts]
            if all(isinstance(item, dict) for item in parsed_many):
                return parsed_many
            return "\n".join(texts)
    if isinstance(payload, dict) and "result" in payload and "jsonrpc" in payload:
        return _unwrap_mcp_result(payload.get("result"))
    return payload


def _maybe_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return text
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return text


def _deleted_flag(payload: Any) -> bool:
    data = _unwrap_mcp_result(payload)
    if isinstance(data, dict):
        for key in ("deleted", "ok", "found", "success"):
            if key in data and data[key] is False:
                return False
        if data.get("deleted") == 0:
            return False
    return True


def _decode_body(response: HTTPResponse) -> Any:
    text = _body_text(response).strip()
    if not text:
        return {}
    if text.startswith("data:"):
        text = _sse_data(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MemoryError("agentmemory returned non-JSON") from exc


def _sse_data(text: str) -> str:
    chunks: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            chunks.append(line[len("data:") :].strip())
    return "\n".join(chunks)


def _body_text(response: HTTPResponse) -> str:
    return response.body.decode("utf-8", errors="replace")


def _mcp_url(base: str) -> str:
    trimmed = base.rstrip("/")
    if trimmed.endswith("/mcp"):
        return trimmed
    return trimmed + "/mcp"
