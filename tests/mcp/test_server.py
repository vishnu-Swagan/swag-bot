"""``swag serve-mcp`` tool listing and injected runner / skills provider."""

from __future__ import annotations

import anyio
import pytest

from swag_bot.interfaces import AutonomyLevel, MCPServerSpec
from swag_bot.mcp.client import SwagMCPClient, in_memory_connector
from swag_bot.mcp.server import build_swag_mcp_server
from swag_bot.safety.policy import DefaultPermissionPolicy

pytest.importorskip("mcp")


def test_serve_mcp_lists_and_calls_injected_tools() -> None:
    seen: dict[str, str] = {}

    def runner(goal: str) -> str:
        seen["goal"] = goal
        return f"done: {goal}"

    def skills() -> list[dict[str, str]]:
        return [{"name": "pdf-processing", "description": "Read PDFs"}]

    server = build_swag_mcp_server(runner=runner, skills_provider=skills)

    async def names() -> list[str]:
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    assert set(anyio.run(names)) == {"swag_run_task", "swag_list_skills"}

    client = SwagMCPClient(
        [MCPServerSpec(name="swag", transport="stdio")],
        policy=DefaultPermissionPolicy(AutonomyLevel.AUTO),
        opener=in_memory_connector({"swag": server}),
    )
    listed = {tool.name for tool in client.list_tools()}
    assert "swag__swag_run_task" in listed
    assert "swag__swag_list_skills" in listed
    assert client.call_tool("swag__swag_run_task", {"goal": "ship it"}) == "done: ship it"
    assert seen["goal"] == "ship it"
    catalog = client.call_tool("swag__swag_list_skills", {})
    assert "pdf-processing" in catalog
    assert "Read PDFs" in catalog
    client.close()


def test_tools_without_injections_stay_callable() -> None:
    server = build_swag_mcp_server()
    client = SwagMCPClient(
        [MCPServerSpec(name="swag", transport="stdio")],
        policy=DefaultPermissionPolicy(AutonomyLevel.AUTO),
        opener=in_memory_connector({"swag": server}),
    )
    summary = client.call_tool("swag__swag_run_task", {"goal": "look around"})
    assert summary == "No task runner is configured."
    assert client.call_tool("swag__swag_list_skills", {}) == "[]"
