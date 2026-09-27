"""MCP client against an in-process server, including permission checks."""

from __future__ import annotations

import pytest

from swag_bot.config import Settings
from swag_bot.errors import SwagError
from swag_bot.interfaces import (
    ActionRequest,
    ApprovalPrompter,
    AutonomyLevel,
    MCPServerSpec,
    ToolCall,
    ToolRegistry,
)
from swag_bot.mcp.client import MCPPermissionDenied, SwagMCPClient, in_memory_connector
from swag_bot.mcp.registry import MCPToolRegistry
from swag_bot.safety.policy import DefaultPermissionPolicy

pytest.importorskip("mcp")
pytest.importorskip("mcp.server.mcpserver")
from mcp.server.mcpserver import MCPServer  # noqa: E402


class _Prompter:
    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.seen: list[ActionRequest] = []

    def prompt(self, action: ActionRequest) -> bool:
        self.seen.append(action)
        return self.allow


def _echo_server() -> tuple[MCPServer, dict[str, int]]:
    server = MCPServer("tiny")
    calls = {"n": 0}

    @server.tool(description="Echo text back.")
    def echo(text: str, api_key: str = "") -> str:
        """Echo text and the api key so the test can see the raw argument."""
        calls["n"] += 1
        return f"{text}|{api_key}"

    return server, calls


def _client(
    server: MCPServer,
    *,
    autonomy: AutonomyLevel,
    prompter: ApprovalPrompter | None = None,
    grants: dict[str, set[str]] | None = None,
) -> SwagMCPClient:
    policy = DefaultPermissionPolicy(autonomy, grants=grants)
    return SwagMCPClient(
        [MCPServerSpec(name="demo", command="unused")],
        policy=policy,
        prompter=prompter,
        opener=in_memory_connector({"demo": server}),
    )


def test_list_and_call_through_policy() -> None:
    server, calls = _echo_server()
    prompter = _Prompter(True)
    client = _client(server, autonomy=AutonomyLevel.ASK_RISKY, prompter=prompter)
    names = [tool.name for tool in client.list_tools()]
    assert "demo__echo" in names
    secret = "sk-testsecretvalue1234567890"
    text = client.call_tool("demo__echo", {"text": "hi", "api_key": secret})
    assert text == f"hi|{secret}"
    assert calls["n"] == 1
    assert prompter.seen
    blob = str(prompter.seen[0].arguments)
    assert secret not in blob
    assert prompter.seen[0].risk.value in {"execute", "destructive", "network"}
    client.close()
    client.close()
    with pytest.raises(SwagError, match="closed"):
        client.list_tools()


def test_denied_call_does_not_run_the_tool() -> None:
    server, calls = _echo_server()
    client = _client(server, autonomy=AutonomyLevel.ASK_ALWAYS, prompter=_Prompter(False))
    with pytest.raises(MCPPermissionDenied):
        client.call_tool("demo__echo", {"text": "hi"})
    assert calls["n"] == 0


def test_auto_does_not_prompt() -> None:
    server, calls = _echo_server()

    class _Boom:
        def prompt(self, action: ActionRequest) -> bool:
            raise AssertionError(action.summary)

    client = _client(server, autonomy=AutonomyLevel.AUTO, prompter=_Boom())
    assert client.call_tool("echo", {"text": "yo"}) == "yo|"
    assert calls["n"] == 1


def test_unknown_tool_raises_keyerror() -> None:
    server, _calls = _echo_server()
    client = _client(server, autonomy=AutonomyLevel.AUTO)
    with pytest.raises(KeyError):
        client.call_tool("missing", {})


def test_registry_adapter() -> None:
    server, calls = _echo_server()
    client = _client(server, autonomy=AutonomyLevel.AUTO)
    registry = MCPToolRegistry(client)
    assert isinstance(registry, ToolRegistry)
    tool = registry.get("demo__echo")
    assert tool.name == "demo__echo"
    text = registry.call(ToolCall(id="1", name="demo__echo", arguments={"text": "z"}))
    assert text == "z|"
    assert calls["n"] == 1
    with pytest.raises(NotImplementedError):
        registry.register(tool, lambda **_kwargs: None)
    with pytest.raises(KeyError):
        registry.get("nope")


def test_build_client_uses_injected_servers() -> None:
    server, _calls = _echo_server()
    from swag_bot.mcp import build_mcp_client

    client = build_mcp_client(
        Settings(autonomy=AutonomyLevel.AUTO),
        servers=[MCPServerSpec(name="demo", transport="stdio")],
        opener=in_memory_connector({"demo": server}),
    )
    assert any(tool.name == "demo__echo" for tool in client.list_tools())


def test_recorder_sees_auto_approval() -> None:
    server, _calls = _echo_server()
    recorded: list[tuple[bool, str]] = []

    def record(action: ActionRequest, approved: bool, approver: str) -> None:
        del action
        recorded.append((approved, approver))

    client = SwagMCPClient(
        [MCPServerSpec(name="demo", command="unused")],
        policy=DefaultPermissionPolicy(AutonomyLevel.AUTO),
        recorder=record,
        opener=in_memory_connector({"demo": server}),
    )
    client.call_tool("demo__echo", {"text": "hi"})
    assert recorded == [(True, "auto")]
