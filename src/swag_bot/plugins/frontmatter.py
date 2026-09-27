"""A small YAML-frontmatter reader for skills, commands, and agents.

The base install does not depend on PyYAML. This parser covers the subset
Agent Skills and Claude Code command files actually use: mappings, one level
of nested mappings, string lists, and ``|`` / ``>`` block scalars.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from swag_bot.plugins.errors import PluginError


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter. Stops at the closing ``---`` and does not read the body."""
    yaml_text = _read_frontmatter_text(path)
    try:
        data = parse_yaml_mapping(yaml_text)
    except PluginError as exc:
        raise PluginError(f"{path}: {exc}") from exc
    return data


def read_markdown_body(path: Path) -> str:
    """Return the markdown after the frontmatter. The frontmatter is not included."""
    text = _read_text(path)
    _yaml, body = split_frontmatter(text, path)
    return body.strip()


def split_frontmatter(text: str, path: Path | None = None) -> tuple[str, str]:
    """Split a markdown document into ``(yaml, body)``."""
    where = f"{path}: " if path is not None else ""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise PluginError(f"{where}missing YAML frontmatter")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            yaml_text = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            return yaml_text, body
    raise PluginError(f"{where}frontmatter is not closed")


def parse_yaml_mapping(text: str) -> dict[str, Any]:
    """Parse a YAML mapping. Raises ``PluginError`` on structure this subset cannot read."""
    lines = text.splitlines()
    parsed, index = _parse_mapping(lines, 0, 0)
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines):
        raise PluginError(f"unexpected frontmatter line: {lines[index].strip()}")
    return parsed


def _read_frontmatter_text(path: Path) -> str:
    """Read only through the closing frontmatter delimiter.

    Bytes after that line are not decoded, so a body that is not UTF-8 does
    not fail discovery.
    """
    where = f"{path}: "
    try:
        handle = path.open("rb")
    except OSError as exc:
        raise PluginError(f"{where}{exc}") from exc
    with handle:
        first = handle.readline()
        if first.startswith(b"\xef\xbb\xbf"):
            first = first.removeprefix(b"\xef\xbb\xbf")
        if first.strip() != b"---":
            raise PluginError(f"{where}missing YAML frontmatter")
        yaml_lines: list[bytes] = []
        closed = False
        for line in handle:
            if line.strip() == b"---":
                closed = True
                break
            yaml_lines.append(line)
    if not closed:
        raise PluginError(f"{where}frontmatter is not closed")
    try:
        return b"".join(yaml_lines).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PluginError(f"{where}frontmatter is not valid UTF-8") from exc


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PluginError(f"{path}: file is not valid UTF-8 ({exc})") from exc
    except OSError as exc:
        raise PluginError(f"{path}: {exc}") from exc


def _parse_mapping(lines: list[str], start: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    index = start
    while index < len(lines):
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#"):
            index += 1
            continue
        current = _indent(raw)
        if current < indent:
            break
        if current > indent:
            raise PluginError(f"unexpected indent in frontmatter: {raw.strip()}")
        key, rest = _split_key(raw.strip())
        index += 1
        if rest in {">", ">-", ">+", "|", "|-", "|+"}:
            block, index = _read_block(lines, index, indent)
            result[key] = _render_block(block, rest[0])
            continue
        if rest == "":
            value, index = _parse_nested(lines, index, indent)
            result[key] = value
            continue
        result[key] = _scalar(rest)
    return result, index


def _parse_nested(lines: list[str], index: int, parent_indent: int) -> tuple[Any, int]:
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return "", index
    current = _indent(lines[index])
    if current <= parent_indent:
        return "", index
    stripped = lines[index].strip()
    if stripped.startswith("- "):
        return _parse_list(lines, index, current)
    return _parse_mapping(lines, index, current)


def _parse_list(lines: list[str], start: int, indent: int) -> tuple[list[str], int]:
    items: list[str] = []
    index = start
    while index < len(lines):
        raw = lines[index]
        if not raw.strip():
            index += 1
            continue
        current = _indent(raw)
        if current < indent:
            break
        stripped = raw.strip()
        if current == indent and stripped.startswith("- "):
            items.append(_scalar(stripped[2:].strip()))
            index += 1
            continue
        if current > indent and items:
            raise PluginError("nested YAML lists in frontmatter are not supported")
        break
    return items, index


def _read_block(lines: list[str], index: int, parent_indent: int) -> tuple[list[str], int]:
    collected: list[str] = []
    content_indent: int | None = None
    while index < len(lines):
        raw = lines[index]
        if raw.strip() == "":
            if content_indent is None:
                index += 1
                continue
            collected.append("")
            index += 1
            continue
        current = _indent(raw)
        if current <= parent_indent:
            break
        if content_indent is None:
            content_indent = current
        if current < content_indent:
            break
        collected.append(raw[content_indent:])
        index += 1
    return collected, index


def _render_block(lines: list[str], style: str) -> str:
    if style == ">":
        paragraphs: list[str] = []
        current: list[str] = []
        for line in lines:
            if line.strip() == "":
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
            else:
                current.append(line.strip())
        if current:
            paragraphs.append(" ".join(current))
        return "\n".join(paragraphs).strip()
    return "\n".join(lines).strip()


def _split_key(stripped: str) -> tuple[str, str]:
    if stripped.startswith("- "):
        raise PluginError(f"YAML list item is not inside a mapping: {stripped}")
    if ":" not in stripped:
        raise PluginError(f"expected 'key: value' in frontmatter, found: {stripped}")
    key, _, rest = stripped.partition(":")
    key = key.strip()
    if not key or any(ch.isspace() for ch in key):
        raise PluginError(f"invalid frontmatter key: {stripped}")
    return key, rest.strip()


def _scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            return _unescape_double(inner)
        return inner
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _unescape_double(value: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            chars.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(escaped, escaped))
            index += 2
            continue
        chars.append(value[index])
        index += 1
    return "".join(chars)


def _indent(raw: str) -> int:
    if raw.startswith("\t") or "\t" in raw[: len(raw) - len(raw.lstrip(" \t"))]:
        raise PluginError("tabs are not allowed in frontmatter indentation")
    return len(raw) - len(raw.lstrip(" "))
