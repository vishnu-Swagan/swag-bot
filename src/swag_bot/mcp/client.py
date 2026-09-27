"""MCP client. Tool calls go through a ``PermissionPolicy`` before they run.

The official ``mcp`` package is imported only when a server is actually
contacted. ``list_tools`` on an empty config does not need it.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from swag_bot.config import Settings
from swag_bot.errors import SwagError
from swag_bot.interfaces import (
    ActionKind,
    ActionRequest,
    ApprovalPrompter,
    AutonomyLevel,
    MCPServerSpec,
    PermissionPolicy,
    RiskLevel,
    TaintTracker,
    Tool,
    default_requires_approval,
)
from swag_bot.mcp.config import effective_transport, load_mcp_servers, resolve_server_spec
from swag_bot.mcp.meta import swag_meta

_SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|credential)"
)
_SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._\-]{8,}|sk-[A-Za-z0-9_\-]{8,}|(api[_-]?key|token|secret|password)\s*[:=]\s*\S+)"
)

ActionRecorder = Callable[[ActionRequest, bool, str], None]
SessionOpener = Callable[[MCPServerSpec], AbstractAsyncContextManager[Any]]


class MCPPermissionDenied(SwagError):
    """The policy or the user refused an MCP tool call."""


class _AutonomyPolicy:
    """Fallback policy used when the caller does not inject one.

    It does not lower ``destructive`` and otherwise trusts ``action.risk``.
    The safety package's policy is the one that raises risk further.
    """

    def __init__(self, autonomy: AutonomyLevel) -> None:
        self._autonomy = autonomy

    @property
    def autonomy(self) -> AutonomyLevel:
        return self._autonomy

    def classify(self, action: ActionRequest) -> RiskLevel:
        if action.risk is RiskLevel.DESTRUCTIVE:
            return RiskLevel.DESTRUCTIVE
        return action.risk

    def requires_approval(self, action: ActionRequest) -> bool:
        return default_requires_approval(self.autonomy, self.classify(action))


class SwagMCPClient:
    """``MCPClient`` for stdio and streamable-HTTP servers.

    Pass ``opener`` to talk to an in-process server in tests. The default
    opener uses the MCP SDK.
    """

    def __init__(
        self,
        servers: list[MCPServerSpec] | tuple[MCPServerSpec, ...],
        *,
        policy: PermissionPolicy,
        prompter: ApprovalPrompter | None = None,
        recorder: ActionRecorder | None = None,
        opener: SessionOpener | None = None,
        taint: TaintTracker | None = None,
    ) -> None:
        self._servers = list(servers)
        self._by_name = {spec.name: spec for spec in self._servers}
        self._policy = policy
        self._prompter = prompter
        self._recorder = recorder
        self._opener = opener or _open_session
        self._taint = taint
        self._closed = False
        self._tools: list[Tool] = []
        self._index: dict[str, tuple[str, str]] = {}

    def list_tools(self) -> list[Tool]:
        """Tools from every configured server. Names are ``server__tool``."""
        self._ensure_open()
        if not self._servers:
            self._tools = []
            self._index = {}
            return []
        self._ensure_sdk()
        tools: list[Tool] = _run_sync(self._list_async)
        return tools

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        authorized: bool = False,
    ) -> str:
        """Invoke a tool. Raise ``KeyError`` if it is unknown.

        ``authorized=True`` means the caller already applied the permission
        policy (the plan-do-verify loop does this before ``ToolRegistry.call``).
        A hard deny is still enforced. The user is not prompted a second time.
        """
        self._ensure_open()
        if name not in self._index:
            self.list_tools()
        try:
            server_name, tool_name = self._index[name]
        except KeyError:
            raise KeyError(name) from None
        spec = self._by_name[server_name]
        action = ActionRequest(
            kind=ActionKind.TOOL.value,
            summary=f"Call MCP tool {name}",
            risk=RiskLevel.EXECUTE,
            target=name,
            arguments={
                "server": server_name,
                "tool": tool_name,
                "arguments": _scrub(dict(arguments)),
            },
        )
        if self._taint is not None:
            action = self._taint.prepare(action, tool=name)
        if authorized:
            self._reject_if_denied(action)
        else:
            self._authorize(action)
        self._ensure_sdk()
        text: str = _run_sync(self._call_async, spec, tool_name, dict(arguments), name)
        return text

    def close(self) -> None:
        """Drop cached tools. Safe to call more than once."""
        self._closed = True
        self._tools = []
        self._index = {}

    async def _list_async(self) -> list[Tool]:
        tools: list[Tool] = []
        qualified: dict[str, tuple[str, str]] = {}
        raw_owners: dict[str, list[tuple[str, str]]] = {}
        metas: dict[str, dict[str, Any]] = {}
        for spec in self._servers:
            async with self._opener(spec) as session:
                listed = await session.list_tools()
                for mcp_tool in listed.tools:
                    public = f"{spec.name}__{mcp_tool.name}"
                    tool = Tool(
                        name=public,
                        description=mcp_tool.description or "",
                        parameters=_parameters(mcp_tool),
                        annotations=_tool_meta(mcp_tool),
                    )
                    tools.append(tool)
                    qualified[public] = (spec.name, mcp_tool.name)
                    raw_owners.setdefault(mcp_tool.name, []).append((spec.name, mcp_tool.name))
                    meta = swag_meta(mcp_tool)
                    if meta:
                        metas[public] = meta
                        if self._taint is not None:
                            self._taint.register_tool(public, meta)
        for raw_name, owners in raw_owners.items():
            if len(owners) == 1 and raw_name not in qualified:
                qualified[raw_name] = owners[0]
                alias_meta = metas.get(f"{owners[0][0]}__{raw_name}")
                if self._taint is not None and alias_meta:
                    self._taint.register_tool(raw_name, alias_meta)
        self._tools = tools
        self._index = qualified
        return list(tools)

    async def _call_async(
        self,
        spec: MCPServerSpec,
        tool_name: str,
        arguments: dict[str, Any],
        public_name: str,
    ) -> str:
        async with self._opener(spec) as session:
            result = await session.call_tool(tool_name, arguments)
        text = _result_text(result)
        if self._taint is not None:
            self._taint.observe_result(public_name, text, swag_meta(result) or None)
        return text

    def _reject_if_denied(self, action: ActionRequest) -> None:
        """Enforce a hard deny after another layer already asked the user."""
        stamped = action.model_copy(update={"risk": self._policy.classify(action)})
        if _decision_of(self._policy, stamped) != "deny":
            return
        self._record(stamped, approved=False, approver="policy")
        raise MCPPermissionDenied(f"MCP tool {action.target} was denied by policy")

    def _authorize(self, action: ActionRequest) -> None:
        risk = self._policy.classify(action)
        stamped = action.model_copy(update={"risk": risk})
        decision = _decision_of(self._policy, stamped)
        if decision == "deny":
            self._record(stamped, approved=False, approver="policy")
            raise MCPPermissionDenied(f"MCP tool {action.target} was denied by policy")
        if decision == "prompt":
            if self._prompter is None:
                self._record(stamped, approved=False, approver="policy")
                raise MCPPermissionDenied(
                    f"MCP tool {action.target} needs approval and no prompter is configured"
                )
            allowed = bool(self._prompter.prompt(stamped))
            self._record(stamped, approved=allowed, approver="user")
            if not allowed:
                raise MCPPermissionDenied(f"MCP tool {action.target} was denied")
            return
        approver = "auto" if self._policy.autonomy is AutonomyLevel.AUTO else "policy"
        self._record(stamped, approved=True, approver=approver)

    def _record(self, action: ActionRequest, *, approved: bool, approver: str) -> None:
        if self._recorder is not None:
            self._recorder(action, approved, approver)

    def _ensure_open(self) -> None:
        if self._closed:
            raise SwagError("MCP client is closed")

    def _ensure_sdk(self) -> None:
        if self._opener is not _open_session:
            return
        try:
            import mcp  # noqa: F401
        except ImportError as exc:
            raise _missing_sdk() from exc


def build_client(
    settings: Settings,
    *,
    policy: PermissionPolicy | None = None,
    prompter: ApprovalPrompter | None = None,
    recorder: ActionRecorder | None = None,
    opener: SessionOpener | None = None,
    servers: list[MCPServerSpec] | None = None,
    taint: TaintTracker | None = None,
) -> SwagMCPClient:
    """Client for ``~/.swag/mcp.json``, or for ``servers`` when that is passed."""
    chosen = list(load_mcp_servers().values()) if servers is None else servers
    active = policy if policy is not None else _AutonomyPolicy(settings.autonomy)
    return SwagMCPClient(
        chosen,
        policy=active,
        prompter=prompter,
        recorder=recorder,
        opener=opener,
        taint=taint,
    )


def in_memory_connector(servers: Mapping[str, Any]) -> SessionOpener:
    """Opener that connects to MCP SDK server objects in this process."""

    def open_server(spec: MCPServerSpec) -> AbstractAsyncContextManager[Any]:
        try:
            server = servers[spec.name]
        except KeyError as exc:
            raise SwagError(f"no in-memory MCP server named {spec.name}") from exc
        return _memory_session(server)

    return open_server


def _decision_of(policy: PermissionPolicy, action: ActionRequest) -> str:
    decide = getattr(policy, "decide", None)
    if callable(decide):
        raw = decide(action)
        value = getattr(raw, "value", raw)
        text = str(value)
        if text in {"allow", "prompt", "deny"}:
            return text
    if policy.requires_approval(action):
        return "prompt"
    return "allow"


def _run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    import anyio

    async def _wrapper() -> Any:
        return await fn(*args, **kwargs)

    return anyio.run(_wrapper)


def _tool_meta(mcp_tool: Any) -> dict[str, Any]:
    """Copy MCP ``meta`` onto ``Tool.annotations``. Missing meta is an empty dict.

    Servers that declare an inverse put ``swagCompensation`` in that map.
    """
    meta = getattr(mcp_tool, "meta", None)
    if not isinstance(meta, dict):
        return {}
    return {str(key): value for key, value in meta.items()}


def _parameters(mcp_tool: Any) -> dict[str, Any]:
    schema: Any = getattr(mcp_tool, "input_schema", None)
    dump = getattr(schema, "model_dump", None)
    if callable(dump):
        schema = dump()
    if isinstance(schema, dict) and schema:
        return schema
    return {"type": "object", "properties": {}}


def _result_text(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else str(block))
    body = "\n".join(part for part in parts if part)
    if body:
        return body
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return json.dumps(structured)
    if getattr(result, "is_error", False):
        return "MCP tool returned an error"
    return ""


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_TEXT.sub("[REDACTED]", value)
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key):
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = _scrub(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


@asynccontextmanager
async def _open_session(spec: MCPServerSpec) -> AsyncIterator[Any]:
    resolved = resolve_server_spec(spec)
    transport = effective_transport(resolved)
    if transport == "http":
        session_cm = _http_session(resolved)
    elif transport == "stdio":
        session_cm = _stdio_session(resolved)
    else:
        raise SwagError(
            f"MCP server {spec.name} uses transport {transport!r}; "
            "only stdio and streamable HTTP are supported"
        )
    async with session_cm as session:
        yield session


@asynccontextmanager
async def _stdio_session(spec: MCPServerSpec) -> AsyncIterator[Any]:
    if not spec.command:
        raise SwagError(f"MCP server {spec.name} has no command")
    try:
        from mcp.client.stdio import stdio_client

        from mcp import ClientSession, StdioServerParameters
    except ImportError as exc:
        raise _missing_sdk() from exc
    params = StdioServerParameters(
        command=spec.command,
        args=list(spec.args),
        env=dict(spec.env) or None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def _http_session(spec: MCPServerSpec) -> AsyncIterator[Any]:
    if not spec.url:
        raise SwagError(f"MCP server {spec.name} has no url")
    try:
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        from mcp import ClientSession
    except ImportError as exc:
        raise _missing_sdk() from exc
    headers = dict(spec.headers) or None
    http_client = create_mcp_http_client(headers=headers)
    async with http_client:
        async with streamable_http_client(spec.url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


@asynccontextmanager
async def _memory_session(server: Any) -> AsyncIterator[Any]:
    try:
        from mcp.client._memory import InMemoryTransport

        from mcp import ClientSession
    except ImportError as exc:
        raise _missing_sdk() from exc
    async with InMemoryTransport(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _missing_sdk() -> SwagError:
    return SwagError(
        "The optional mcp package is not installed. Install it with: pip install 'swag-bot[mcp]'"
    )
