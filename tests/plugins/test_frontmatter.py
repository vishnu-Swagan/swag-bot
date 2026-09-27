"""Frontmatter parsing without a YAML dependency."""

from __future__ import annotations

from pathlib import Path

import pytest

from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.frontmatter import parse_yaml_mapping, read_frontmatter, split_frontmatter


def test_folded_description_and_metadata() -> None:
    parsed = parse_yaml_mapping(
        "\n".join(
            [
                "name: demo-skill",
                "description: >",
                "  Extract text from PDFs.",
                "  Use when the user mentions PDFs.",
                "metadata:",
                "  author: ada",
                '  version: "1.0"',
                "allowed-tools: Read Bash",
            ]
        )
    )
    assert parsed["name"] == "demo-skill"
    assert parsed["description"] == "Extract text from PDFs. Use when the user mentions PDFs."
    assert parsed["metadata"] == {"author": "ada", "version": "1.0"}
    assert parsed["allowed-tools"] == "Read Bash"


def test_literal_block_and_quoted_scalar() -> None:
    parsed = parse_yaml_mapping('title: "line\\nnext"\nbody: |\n  one\n  two\n')
    assert parsed["title"] == "line\nnext"
    assert parsed["body"] == "one\ntwo"


def test_string_list() -> None:
    parsed = parse_yaml_mapping("tools:\n  - Read\n  - Grep\n")
    assert parsed["tools"] == ["Read", "Grep"]


def test_split_frontmatter_drops_header(tmp_path: Path) -> None:
    text = "---\nname: demo-skill\ndescription: Hello there.\n---\n\n# Body\n"
    yaml_text, body = split_frontmatter(text, tmp_path / "SKILL.md")
    assert "name: demo-skill" in yaml_text
    assert body.strip() == "# Body"


def test_reader_stops_before_invalid_body(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    with path.open("wb") as handle:
        handle.write(b"---\nname: demo-skill\ndescription: Hello there friend.\n---\n")
        handle.write(b"\xff\xfe not utf-8")
    data = read_frontmatter(path)
    assert data["name"] == "demo-skill"
    assert data["description"] == "Hello there friend."


def test_unclosed_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: demo-skill\n", encoding="utf-8")
    with pytest.raises(PluginError, match="not closed"):
        read_frontmatter(path)


def test_tabs_are_rejected() -> None:
    with pytest.raises(PluginError, match="tabs"):
        parse_yaml_mapping("metadata:\n\tauthor: ada\n")
