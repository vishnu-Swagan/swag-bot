"""Loading plugins, skills, commands, agents, and MCP config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.interfaces import MCPServerSpec, Plugin, PluginRegistry, Skill
from swag_bot.plugins.catalog import PluginRegistry as LoadedRegistry
from swag_bot.plugins.catalog import build_registry
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.loader import load_plugin, load_skill_directory
from tests.plugins.helpers import write_plugin, write_skill

EXAMPLE = Path(__file__).resolve().parents[2] / "plugins" / "example-github-helper"


def test_example_plugin_loads_without_touching_the_network() -> None:
    plugin = load_plugin(EXAMPLE)
    assert isinstance(plugin, Plugin)
    assert plugin.manifest.name == "example-github-helper"
    assert plugin.manifest.version == "0.1.0"
    assert plugin.manifest.permissions == ["network", "mcp", "secrets"]
    assert plugin.manifest.display_name == "GitHub Helper"

    skills = plugin.list_skills()
    assert [meta.name for meta in skills] == ["github-issue-helper"]
    assert "GitHub issues" in skills[0].description
    skill = plugin.load_skill("github-issue-helper")
    assert isinstance(skill, Skill)
    assert skill.instructions_loaded is False
    body = skill.instructions()
    assert skill.instructions_loaded is True
    assert "issue-checklist.md" in body
    assert "name: github-issue-helper" not in body
    assert skill.resources() == ["references/issue-checklist.md"]
    assert "Summary" in skill.read_resource("references/issue-checklist.md")

    commands = plugin.list_commands()
    assert commands[0].name == "gh-issue"
    assert commands[0].body == ""
    assert commands[0].argument_hint == "[title and context]"
    rendered = plugin.load_command("gh-issue")
    assert "$ARGUMENTS" in rendered.body

    agents = plugin.list_agents()
    assert agents[0].name == "issue-triage"
    assert agents[0].body == ""
    assert "Do not post" in plugin.load_agent("issue-triage").body

    servers = plugin.list_mcp_servers()
    assert len(servers) == 1
    server = servers[0]
    assert isinstance(server, MCPServerSpec)
    assert server.name == "github"
    assert server.command == "docker"
    assert server.transport == "stdio"
    assert "ghcr.io/github/github-mcp-server" in server.args
    assert server.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "${GITHUB_PERSONAL_ACCESS_TOKEN}"
    assert "ghp_" not in json.dumps(server.model_dump())
    assert "github_pat_" not in json.dumps(server.model_dump())


def test_progressive_loading_ignores_body_until_instructions(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin", skill_body="ORIGINAL BODY\n")
    plugin = load_plugin(root)
    plugin.list_skills()
    skill = plugin.load_skill("demo-skill")
    assert skill.instructions_loaded is False
    skill_md = root / "skills" / "demo-skill" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(text.replace("ORIGINAL BODY", "UPDATED BODY"), encoding="utf-8")
    assert "UPDATED BODY" in skill.instructions()
    assert "ORIGINAL BODY" not in skill.instructions()

    notes = root / "skills" / "demo-skill" / "references" / "notes.md"
    assert skill.resources() == ["references/notes.md"]
    notes.write_text("fresh note\n", encoding="utf-8")
    assert skill.read_resource("references/notes.md") == "fresh note\n"


def test_invalid_utf8_body_is_not_read_at_discovery(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin")
    skill_md = root / "skills" / "demo-skill" / "SKILL.md"
    with skill_md.open("wb") as handle:
        handle.write(b"---\nname: demo-skill\ndescription: Hello there friend.\n---\n")
        handle.write(b"\xff\xfe")
    plugin = load_plugin(root)
    meta = plugin.list_skills()[0]
    assert meta.name == "demo-skill"
    skill = plugin.load_skill("demo-skill")
    with pytest.raises(PluginError, match="UTF-8"):
        skill.instructions()


def test_resource_paths_cannot_escape(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin")
    skill = load_plugin(root).load_skill("demo-skill")
    for relative in ("../SKILL.md", "/etc/passwd", "SKILL.md", "references/../../secrets.txt", ""):
        with pytest.raises(FileNotFoundError):
            skill.read_resource(relative)


def test_malformed_manifests(tmp_path: Path) -> None:
    root = tmp_path / "broken"
    manifest = root / ".claude-plugin"
    manifest.mkdir(parents=True)
    (manifest / "plugin.json").write_text("{", encoding="utf-8")
    with pytest.raises(PluginError, match="invalid JSON"):
        load_plugin(root)

    (manifest / "plugin.json").write_text(json.dumps({"version": "1"}), encoding="utf-8")
    with pytest.raises(PluginError, match="invalid plugin manifest"):
        load_plugin(root)

    (manifest / "plugin.json").write_text(
        json.dumps({"name": "bad name", "permissions": ["ok"]}),
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="invalid plugin manifest"):
        load_plugin(root)

    (manifest / "plugin.json").write_text(
        json.dumps({"name": "ok", "permissions": ["has space"]}),
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="invalid plugin manifest"):
        load_plugin(root)

    with pytest.raises(PluginError, match="not a directory"):
        load_plugin(tmp_path / "missing")


def test_unknown_manifest_keys_are_kept(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin", extra={"futureField": {"kept": True}})
    plugin = load_plugin(root)
    assert plugin.manifest.model_extra is not None
    assert plugin.manifest.model_extra["futureField"] == {"kept": True}


def test_skill_name_must_match_directory(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin", skill_name="demo-skill")
    skill_md = root / "skills" / "demo-skill" / "SKILL.md"
    skill_md.write_text(
        "---\nname: other-skill\ndescription: Not the directory name here.\n---\n\nBody\n",
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="does not match"):
        load_plugin(root).list_skills()


def test_component_path_cannot_escape(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin", extra={"skills": "../outside"})
    with pytest.raises(PluginError, match="stay inside"):
        load_plugin(root).list_skills()


def test_command_arguments_and_omitted_placeholder(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin", command_body="Fix $ARGUMENTS now.\n")
    plugin = load_plugin(root)
    assert plugin.list_commands()[0].body == ""
    from swag_bot.plugins.loader import substitute_arguments

    rendered = substitute_arguments(plugin.load_command("demo").body, "the login bug")
    assert rendered == "Fix the login bug now."
    appended = substitute_arguments("No placeholder.\n", "extra")
    assert appended.endswith("extra\n")
    assert substitute_arguments("No placeholder.\n", "   ") == "No placeholder.\n"


def test_inline_and_http_mcp(tmp_path: Path) -> None:
    root = write_plugin(
        tmp_path / "plugin",
        extra={
            "mcpServers": {
                "remote": {"url": "https://example.com/mcp", "type": "http"},
                "local": {"command": "echo", "args": ["hi"], "env": {"TOKEN": "${TOKEN}"}},
            }
        },
    )
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"ignored": {"command": "nope"}}}),
        encoding="utf-8",
    )
    servers = {spec.name: spec for spec in load_plugin(root).list_mcp_servers()}
    assert set(servers) == {"remote", "local"}
    assert servers["remote"].transport == "http"
    assert servers["remote"].url == "https://example.com/mcp"
    assert servers["local"].transport == "stdio"
    assert servers["local"].env["TOKEN"] == "${TOKEN}"


def test_default_mcp_file_when_manifest_omits_it(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin")
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"docs": {"url": "https://example.com/sse", "type": "sse"}}}),
        encoding="utf-8",
    )
    servers = load_plugin(root).list_mcp_servers()
    assert servers[0].name == "docs"
    assert servers[0].transport == "sse"


def test_malformed_mcp_env_must_be_strings(tmp_path: Path) -> None:
    root = write_plugin(tmp_path / "plugin")
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"docs": {"command": "echo", "env": {"TOKEN": 1}}}}),
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="env values must be strings"):
        load_plugin(root).list_mcp_servers()


def test_standalone_skills_and_registry(tmp_path: Path) -> None:
    from swag_bot.config import Settings

    home = tmp_path / "home"
    project = tmp_path / "project"
    write_skill(
        project / ".agents" / "skills" / "pdf-processing",
        name="pdf-processing",
        description="Extract text from PDF files. Use when the user mentions PDFs.",
    )
    write_skill(
        home / "skills" / "pdf-processing",
        name="pdf-processing",
        description="This user copy should lose to the project skill.",
    )
    write_skill(
        home / "skills" / "notes",
        name="notes",
        description="Take notes. Use when the user mentions notes.",
    )
    plugin_root = write_plugin(
        tmp_path / "plugins" / "demo-plugin",
        skill_name="demo-skill",
        skill_description="Demo skill used in tests. Use when the user mentions demos.",
    )
    settings = Settings(plugin_dirs=[str(plugin_root.parent)])
    registry = build_registry(settings, cwd=project, home=home)
    assert isinstance(registry, PluginRegistry)
    assert isinstance(registry, LoadedRegistry)
    names = [meta.name for meta in registry.list_skills()]
    assert names == ["demo-skill", "pdf-processing", "notes"]
    pdf = registry.load_skill("pdf-processing")
    assert "Extract text" in pdf.meta.description
    with pytest.raises(KeyError):
        registry.load_skill("missing")
    command = registry.load_command("demo", "the widget")
    assert "the widget" in command.body
    assert registry.list_commands()[0].body == ""


def test_skill_directory_name_is_checked_for_standalone(tmp_path: Path) -> None:
    directory = tmp_path / "wrong-name"
    write_skill(
        directory,
        name="right-name",
        description="A perfectly fine description for a skill.",
    )
    with pytest.raises(PluginError, match="does not match"):
        load_skill_directory(directory)
