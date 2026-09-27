"""Browser MCP tools advertise grants. Skipped unless the mcp extra is installed."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("mcp.server.mcpserver")

from swag_bot.browser.server import build_browser_mcp_server  # noqa: E402
from swag_bot.browser.service import BrowserService  # noqa: E402
from swag_bot.interfaces import AutonomyLevel, MCPServerSpec  # noqa: E402
from swag_bot.mcp.client import (  # noqa: E402
    MCPPermissionDenied,
    SwagMCPClient,
    in_memory_connector,
)
from swag_bot.safety.policy import DefaultPermissionPolicy  # noqa: E402
from tests.browser.fake_page import FakePage  # noqa: E402


def _client(server: object, grants: set[str]) -> SwagMCPClient:
    policy = DefaultPermissionPolicy(AutonomyLevel.AUTO, grants={"browser": grants})
    return SwagMCPClient(
        [
            MCPServerSpec(
                name="browser",
                command="swag",
                args=["browser-mcp"],
                plugin="browser",
            )
        ],
        policy=policy,
        opener=in_memory_connector({"browser": server}),
    )


def test_listed_tools_carry_plugin_grants_and_calls_honor_them(tmp_path: Path) -> None:
    page = FakePage()
    service = BrowserService(opener=lambda: page, output_dir=tmp_path, timeout=5)
    server = build_browser_mcp_server(service)
    client = _client(server, {"network", "mcp", "filesystem.write"})
    try:
        tools = {tool.name: tool for tool in client.list_tools()}
        assert tools["browser__snapshot"].risk_hint == "read"
        assert tools["browser__snapshot"].permission_hint == "mcp"
        assert tools["browser__snapshot"].plugin == "browser"
        assert tools["browser__navigate"].risk_hint == "network"
        assert tools["browser__navigate"].permission_hint == "network"
        assert tools["browser__submit"].permission_hint == "network"
        assert tools["browser__screenshot"].permission_hint == "filesystem.write"
        opened = client.call_tool(
            "browser__navigate",
            {"url": "https://example.com"},
            authorized=True,
        )
        assert "new domain" in opened
        assert "example.com" in page.url()
    finally:
        client.close()
        service.close()


def test_authorized_call_still_denies_a_missing_network_grant(tmp_path: Path) -> None:
    page = FakePage()
    service = BrowserService(opener=lambda: page, output_dir=tmp_path, timeout=5)
    server = build_browser_mcp_server(service)
    client = _client(server, {"mcp"})
    try:
        client.list_tools()
        with pytest.raises(MCPPermissionDenied):
            client.call_tool(
                "browser__download",
                {"url": "https://example.com/file.txt", "path": "file.txt"},
                authorized=True,
            )
        assert page.downloads == []
    finally:
        client.close()
        service.close()
