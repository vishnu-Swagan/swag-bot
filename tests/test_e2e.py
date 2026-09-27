"""End-to-end ``swag run`` and a smoke check of every CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.config import Settings, save_settings
from swag_bot.memory import get_memory_store
from tests.cli_output import visible as _visible
from tests.core.support import plan_json, verdict
from tests.fakes import FakeLLMClient
from tests.plugins.helpers import write_plugin

runner = CliRunner()

_COMMANDS = (
    ["--help"],
    ["version"],
    ["doctor"],
    ["run", "--help"],
    ["serve-mcp", "--help"],
    ["plugin", "--help"],
    ["plugin", "list"],
    ["plugin", "install", "--help"],
    ["plugin", "enable", "--help"],
    ["plugin", "disable", "--help"],
    ["plugin", "remove", "--help"],
    ["plugin", "info", "--help"],
    ["plugin", "show", "--help"],
    ["plugin", "validate", "--help"],
    ["skill", "--help"],
    ["skill", "list"],
    ["safety", "--help"],
    ["safety", "log"],
    ["safety", "policy"],
    ["safety", "grant", "--help"],
    ["safety", "revoke", "--help"],
    ["mcp", "--help"],
    ["mcp", "list"],
    ["mcp", "tools"],
    ["mcp", "add", "--help"],
    ["mcp", "remove", "--help"],
    ["mcp", "serve", "--help"],
    ["model", "--help"],
    ["model", "list"],
    ["model", "test", "--help"],
    ["model", "probe", "--help"],
    ["model", "set", "--help"],
    ["memory", "--help"],
    ["memory", "add", "--help"],
    ["memory", "search", "--help"],
    ["memory", "list"],
    ["memory", "forget", "--help"],
)


def test_every_command_responds() -> None:
    for args in _COMMANDS:
        result = runner.invoke(app, list(args))
        assert result.exit_code == 0, f"{args}: {_visible(result)}"


def test_swag_run_selects_a_skill_saves_memory_and_writes_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = write_plugin(
        tmp_path / "plugin",
        name="github-helper",
        skill_name="github-issue",
        skill_description="Draft a reply for a github issue.",
        skill_body="SKILL BODY: check the issue checklist before posting.\n",
        permissions=["mcp"],
    )
    save_settings(Settings(plugin_dirs=[str(plugin)]))
    get_memory_store().add("Prior note: github issue login timeout")

    summary = "Finished the github issue."
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "triage",
                        "title": "Triage the issue",
                        "instruction": "Read the skill and draft a reply",
                        "success_criteria": "a reply was drafted",
                        "checks": [
                            {
                                "id": "noted",
                                "kind": "command",
                                "command": "true",
                                "expected_exit": 0,
                            }
                        ],
                    }
                ]
            ),
            "Noted the github issue.",
            verdict(True, "reply drafted"),
            summary,
        ]
    )
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            "github issue",
            "--output-dir",
            str(out),
            "--autonomy",
            "auto",
            "--max-attempts",
            "1",
        ],
    )
    text = _visible(result)
    assert result.exit_code == 0, text
    written = (out / "summary.md").read_text(encoding="utf-8")
    assert summary in written
    assert (out / "plan.json").is_file()
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    assert plan["goal"] == "github issue"
    assert plan["steps"][0]["status"] == "done"

    planner = llm.messages[0]
    user = planner[-1].content or ""
    assert "SKILL BODY: check the issue checklist before posting." in user
    assert "Prior note: github issue login timeout" in user
    assert "github-issue" in user

    saved = get_memory_store().search(summary)
    assert saved
    assert any(item.metadata.get("kind") == "run-summary" for item in saved)


def test_run_merges_plugin_and_config_mcp_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from swag_bot.errors import SwagError
    from swag_bot.interfaces import MCPServerSpec

    plugin = write_plugin(
        tmp_path / "plugin",
        name="remote-tools",
        extra={
            "mcpServers": {
                "from-plugin": {"command": "echo", "args": ["plugin"]},
            }
        },
    )
    save_settings(Settings(plugin_dirs=[str(plugin)]))
    mcp_path = Path(os.environ["SWAG_HOME"]) / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "from-plugin": {"command": "echo", "args": ["config-wins"]},
                    "from-config": {"url": "https://example.invalid/mcp", "type": "http"},
                }
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, MCPServerSpec] = {}

    def capture(settings: object, **kwargs: object) -> object:
        servers = kwargs.get("servers")
        assert isinstance(servers, list)
        for spec in servers:
            assert isinstance(spec, MCPServerSpec)
            seen[spec.name] = spec
        raise SwagError("mcp down")

    monkeypatch.setattr("swag_bot.core.cli.build_mcp_client", capture)
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "look",
                        "title": "Look",
                        "instruction": "Look",
                        "success_criteria": "looked",
                    }
                ]
            )
        ]
    )
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    result = runner.invoke(
        app,
        [
            "run",
            "look around",
            "--dry-run",
            "--output-dir",
            str(tmp_path / "out"),
            "--autonomy",
            "auto",
        ],
    )
    assert result.exit_code == 0, _visible(result)
    assert "MCP tools were not loaded" in _visible(result)
    assert set(seen) == {"from-plugin", "from-config"}
    assert seen["from-plugin"].args == ["config-wins"]
    assert seen["from-config"].url == "https://example.invalid/mcp"


def test_serve_mcp_wires_runner_and_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = write_plugin(
        tmp_path / "plugin",
        name="github-helper",
        skill_name="github-issue",
        skill_description="Draft a reply for a github issue.",
        skill_body="SKILL BODY: check the issue checklist before posting.\n",
    )
    save_settings(Settings(plugin_dirs=[str(plugin)]))
    captured: dict[str, object] = {}

    class _Server:
        def run(self, *args: object, **kwargs: object) -> None:
            captured["transport"] = args

    def build(**kwargs: object) -> _Server:
        captured["kwargs"] = kwargs
        return _Server()

    monkeypatch.setattr("swag_bot.mcp.server.build_swag_mcp_server", build)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["serve-mcp"])
    assert result.exit_code == 0, _visible(result)
    assert captured["transport"] == ("stdio",)
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    skills = kwargs["skills_provider"]
    assert callable(skills)
    names = [item.name for item in skills()]
    assert "github-issue" in names

    summary = "Finished the github issue."
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "triage",
                        "title": "Triage",
                        "instruction": "Triage",
                        "success_criteria": "done",
                    }
                ]
            ),
            "Noted it.",
            verdict(True, "done"),
            summary,
        ]
    )
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    task = kwargs["runner"]
    assert callable(task)
    assert summary in task("github issue")
    assert (tmp_path / "swag-output").is_dir()
