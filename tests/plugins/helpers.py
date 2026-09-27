"""Builders for plugin directories used by the plugin tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_plugin(
    root: Path,
    *,
    name: str = "demo-plugin",
    version: str = "1.0.0",
    description: str = "A demo plugin for tests.",
    permissions: list[str] | None = None,
    default_enabled: bool = True,
    skill: bool = True,
    skill_name: str = "demo-skill",
    skill_description: str = "Demo skill used in tests. Use when the user mentions demos.",
    skill_body: str = "Do the demo task.\n",
    command: bool = True,
    command_name: str = "demo",
    command_body: str = "Run the demo for $ARGUMENTS.\n",
    agent: bool = False,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a minimal valid plugin under ``root`` and return ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "name": name,
        "version": version,
        "description": description,
        "permissions": ["filesystem.read"] if permissions is None else permissions,
        "defaultEnabled": default_enabled,
    }
    if extra:
        manifest.update(extra)
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    if skill:
        skill_dir = root / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    f"name: {skill_name}",
                    f"description: {skill_description}",
                    "---",
                    "",
                    skill_body,
                ]
            ),
            encoding="utf-8",
        )
        notes = skill_dir / "references"
        notes.mkdir(parents=True, exist_ok=True)
        (notes / "notes.md").write_text("note body\n", encoding="utf-8")
    if command:
        commands = root / "commands"
        commands.mkdir(parents=True, exist_ok=True)
        (commands / f"{command_name}.md").write_text(
            "\n".join(
                [
                    "---",
                    "description: Demo slash command",
                    "argument-hint: \"[text]\"",
                    "---",
                    "",
                    command_body,
                ]
            ),
            encoding="utf-8",
        )
    if agent:
        agents = root / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "helper.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: helper",
                    "description: A demo sub-agent.",
                    "tools: Read",
                    "---",
                    "",
                    "You help with the demo.\n",
                ]
            ),
            encoding="utf-8",
        )
    return root


def write_skill(
    directory: Path,
    *,
    name: str,
    description: str,
    body: str = "Do the thing.\n",
) -> Path:
    """Write one standalone skill directory."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8",
    )
    return directory
