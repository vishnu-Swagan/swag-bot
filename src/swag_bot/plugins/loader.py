"""Load a Cowork / Claude Code plugin directory.

Discovery reads manifest JSON and YAML frontmatter only. ``SKILL.md`` bodies,
slash-command prompts, sub-agent prompts, and bundled resource files are read
when something asks for them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from swag_bot.interfaces import (
    AgentDefinition,
    MCPServerSpec,
    PluginManifest,
    SkillMeta,
    SlashCommand,
)
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.frontmatter import read_frontmatter, read_markdown_body
from swag_bot.plugins.mcp_config import load_mcp_file, parse_mcp_map

_RESOURCE_DIRS = ("scripts", "references", "assets")
_MANIFEST = Path(".claude-plugin") / "plugin.json"


class FileSkill:
    """One skill directory. Metadata is kept; the body is read on demand."""

    def __init__(self, directory: Path, meta: SkillMeta) -> None:
        self._directory = directory
        self._meta = meta
        self.instructions_loaded = False

    @property
    def meta(self) -> SkillMeta:
        return self._meta

    def instructions(self) -> str:
        """Return the ``SKILL.md`` body with frontmatter removed."""
        self.instructions_loaded = True
        return read_markdown_body(self._directory / "SKILL.md")

    def resources(self) -> list[str]:
        """Relative paths under ``scripts/``, ``references/``, and ``assets/``."""
        found: list[str] = []
        root = self._directory.resolve()
        for folder in _RESOURCE_DIRS:
            base = self._directory / folder
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                if _escapes(root, path):
                    continue
                found.append(path.relative_to(self._directory).as_posix())
        return found

    def read_resource(self, relative_path: str) -> str:
        """Read one bundled file. Raise ``FileNotFoundError`` if it is missing or unsafe."""
        target = _resource_path(self._directory, relative_path)
        try:
            return target.read_text(encoding="utf-8")
        except OSError as exc:
            raise FileNotFoundError(relative_path) from exc


class LoadedPlugin:
    """A plugin root with a parsed manifest and lazily indexed components."""

    def __init__(self, root: Path, manifest: PluginManifest) -> None:
        self._root = root.resolve()
        self._manifest = manifest
        self._skills: dict[str, FileSkill] | None = None
        self._commands: dict[str, Path] | None = None
        self._agents: dict[str, Path] | None = None
        self._mcp: list[MCPServerSpec] | None = None

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    @property
    def root(self) -> Path:
        return self._root

    def list_skills(self) -> list[SkillMeta]:
        """Level-1 metadata. Does not read ``SKILL.md`` bodies."""
        return [skill.meta for skill in self._index_skills().values()]

    def load_skill(self, name: str) -> FileSkill:
        """Return one skill. Raise ``KeyError`` if this plugin does not provide it."""
        try:
            return self._index_skills()[name]
        except KeyError:
            raise KeyError(name) from None

    def list_commands(self) -> list[SlashCommand]:
        """Slash commands with empty bodies."""
        return [self._command_meta(name, path) for name, path in self._index_commands().items()]

    def load_command(self, name: str) -> SlashCommand:
        """Return one command including its prompt body, before argument substitution."""
        path = self._index_commands().get(name)
        if path is None:
            raise KeyError(name)
        command = self._command_meta(name, path)
        return command.model_copy(update={"body": read_markdown_body(path)})

    def list_agents(self) -> list[AgentDefinition]:
        """Sub-agents with empty bodies."""
        return [self._agent_meta(name, path) for name, path in self._index_agents().items()]

    def load_agent(self, name: str) -> AgentDefinition:
        """Return one sub-agent including its prompt body."""
        path = self._index_agents().get(name)
        if path is None:
            raise KeyError(name)
        agent = self._agent_meta(name, path)
        return agent.model_copy(update={"body": read_markdown_body(path)})

    def list_mcp_servers(self) -> list[MCPServerSpec]:
        """Parsed MCP connector config. Servers are not started."""
        if self._mcp is None:
            self._mcp = _load_mcp_servers(self._root, self._manifest)
        return list(self._mcp)

    def _index_skills(self) -> dict[str, FileSkill]:
        if self._skills is None:
            skills: dict[str, FileSkill] = {}
            for directory in _skill_directories(self._root, self._manifest.skills):
                skill = load_skill_directory(directory)
                if skill.meta.name in skills:
                    raise PluginError(f"duplicate skill name {skill.meta.name!r} in {self._root}")
                skills[skill.meta.name] = skill
            self._skills = skills
        return self._skills

    def _index_commands(self) -> dict[str, Path]:
        if self._commands is None:
            self._commands = _index_markdown(self._root, self._manifest.commands, "commands")
        return self._commands

    def _index_agents(self) -> dict[str, Path]:
        if self._agents is None:
            self._agents = _index_markdown(self._root, self._manifest.agents, "agents")
        return self._agents

    def _command_meta(self, name: str, path: Path) -> SlashCommand:
        data = read_frontmatter(path)
        payload: dict[str, Any] = {
            "name": _explicit_name(data) or name,
            "description": _as_text(data.get("description")),
            "body": "",
        }
        hint = data.get("argument-hint", data.get("argument_hint"))
        tools = data.get("allowed-tools", data.get("allowed_tools"))
        if hint is not None:
            payload["argument-hint"] = _as_text(hint)
        if tools is not None:
            payload["allowed-tools"] = _join_tools(tools)
        return SlashCommand.model_validate(payload)

    def _agent_meta(self, name: str, path: Path) -> AgentDefinition:
        data = read_frontmatter(path)
        tools = data.get("tools")
        model = data.get("model")
        return AgentDefinition(
            name=_explicit_name(data) or name,
            description=_as_text(data.get("description")),
            body="",
            tools=_join_tools(tools) if tools is not None else None,
            model=model if isinstance(model, str) and model else None,
        )


def load_plugin(root: Path, *, manifest: PluginManifest | None = None) -> LoadedPlugin:
    """Load one plugin directory.

    ``root`` is the directory that contains ``.claude-plugin/``. A missing
    manifest is an error unless ``manifest`` is provided (marketplace
    ``strict: false`` entries).
    """
    plugin_root = root.expanduser().resolve()
    if not plugin_root.is_dir():
        raise PluginError(f"plugin root is not a directory: {root}")
    parsed = manifest if manifest is not None else read_manifest(plugin_root)
    if manifest is None and not (plugin_root / _MANIFEST).is_file():
        raise PluginError(f"plugin is missing {_MANIFEST.as_posix()}: {plugin_root}")
    return LoadedPlugin(plugin_root, parsed)


def read_manifest(root: Path) -> PluginManifest:
    """Read and validate ``.claude-plugin/plugin.json``."""
    path = root / _MANIFEST
    if not path.is_file():
        raise PluginError(f"plugin is missing { _MANIFEST.as_posix() }: {root}")
    data = _read_json_object(path)
    try:
        return PluginManifest.from_plugin_json(data)
    except ValidationError as exc:
        raise PluginError(f"{path}: invalid plugin manifest: {exc}") from exc


def load_skill_directory(directory: Path) -> FileSkill:
    """Load one Agent Skill directory. The parent directory name must match ``name``."""
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        raise PluginError(f"skill is missing SKILL.md: {directory}")
    data = _prepare_skill_data(read_frontmatter(skill_md), skill_md)
    data["location"] = directory
    try:
        meta = SkillMeta.model_validate(data)
    except ValidationError as exc:
        raise PluginError(f"{skill_md}: invalid skill metadata: {exc}") from exc
    if directory.name != meta.name:
        raise PluginError(
            f"{skill_md}: skill name {meta.name!r} does not match "
            f"parent directory {directory.name!r}"
        )
    return FileSkill(directory, meta)


def discover_skill_directories(root: Path) -> list[Path]:
    """Skill directories directly under ``root`` (each contains ``SKILL.md``)."""
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            found.append(child)
    return found


def plugins_from_path(path: Path) -> list[LoadedPlugin]:
    """Load ``path`` when it is a plugin, otherwise load plugin children."""
    if not path.exists():
        return []
    if (path / _MANIFEST).is_file():
        return [load_plugin(path)]
    if not path.is_dir():
        return []
    found: list[LoadedPlugin] = []
    for child in sorted(path.iterdir()):
        if child.is_dir() and (child / _MANIFEST).is_file():
            found.append(load_plugin(child))
    return found


def substitute_arguments(body: str, arguments: str) -> str:
    """Replace ``$ARGUMENTS`` in a slash-command prompt.

    When the placeholder is absent and ``arguments`` is non-empty, the
    arguments are appended so the model still sees them.
    """
    if "$ARGUMENTS" in body:
        return body.replace("$ARGUMENTS", arguments)
    if arguments.strip():
        return body.rstrip() + "\n\n" + arguments.strip() + "\n"
    return body


def _prepare_skill_data(data: dict[str, Any], path: Path) -> dict[str, Any]:
    prepared = dict(data)
    metadata = prepared.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise PluginError(f"{path}: skill metadata must be a mapping")
        coerced: dict[str, str] = {}
        for key, value in metadata.items():
            if isinstance(value, (dict, list)):
                raise PluginError(f"{path}: skill metadata values must be strings")
            coerced[str(key)] = "" if value is None else str(value)
        prepared["metadata"] = coerced
    return prepared


def _skill_directories(root: Path, specs: str | list[str] | None) -> list[Path]:
    if specs is None:
        default = root / "skills"
        if not default.exists():
            return []
        return _directories_from_spec(root, "./skills", "skills")
    paths = [specs] if isinstance(specs, str) else list(specs)
    found: list[Path] = []
    for spec in paths:
        found.extend(_directories_from_spec(root, spec, "skills"))
    return found


def _directories_from_spec(root: Path, spec: str, kind: str) -> list[Path]:
    if not isinstance(spec, str) or not spec:
        raise PluginError(f"{kind} path must be a string")
    path = _safe_component(root, spec)
    if not path.exists():
        raise PluginError(f"{kind} path does not exist: {spec}")
    if (path / "SKILL.md").is_file():
        return [path]
    if path.is_dir():
        return discover_skill_directories(path)
    raise PluginError(f"{kind} path is not a directory: {spec}")


def _index_markdown(root: Path, specs: str | list[str] | None, kind: str) -> dict[str, Path]:
    indexed: dict[str, Path] = {}
    for path in _markdown_files(root, specs, kind):
        name = _markdown_name(path, root, specs, kind)
        data = read_frontmatter(path)
        explicit = _explicit_name(data)
        chosen = explicit or name
        if chosen in indexed:
            raise PluginError(f"duplicate {kind[:-1]} name {chosen!r} in {root}")
        indexed[chosen] = path
    return indexed


def _markdown_files(root: Path, specs: str | list[str] | None, kind: str) -> list[Path]:
    if specs is None:
        default = root / kind
        if not default.exists():
            return []
        specs = f"./{kind}"
    paths = [specs] if isinstance(specs, str) else list(specs)
    files: list[Path] = []
    for spec in paths:
        if not isinstance(spec, str) or not spec:
            raise PluginError(f"{kind} path must be a string")
        path = _safe_component(root, spec)
        if not path.exists():
            raise PluginError(f"{kind} path does not exist: {spec}")
        if path.is_file():
            if path.suffix != ".md":
                raise PluginError(f"{kind} file must be markdown: {spec}")
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(item for item in path.rglob("*.md") if item.is_file()))
        else:
            raise PluginError(f"{kind} path is not a file or directory: {spec}")
    return files


def _markdown_name(path: Path, root: Path, specs: str | list[str] | None, kind: str) -> str:
    bases: list[Path] = []
    if specs is None:
        bases.append(root / kind)
    else:
        declared = [specs] if isinstance(specs, str) else list(specs)
        for spec in declared:
            if isinstance(spec, str):
                candidate = _safe_component(root, spec)
                bases.append(candidate if candidate.is_dir() else candidate.parent)
    for base in bases:
        try:
            relative = path.resolve().relative_to(base.resolve())
        except ValueError:
            continue
        stem = relative.as_posix()
        if stem.endswith(".md"):
            stem = stem[: -len(".md")]
        return stem.replace("/", ":")
    return path.stem


def _load_mcp_servers(root: Path, manifest: PluginManifest) -> list[MCPServerSpec]:
    raw = manifest.mcp_servers
    if raw is None:
        default = root / ".mcp.json"
        if default.is_file():
            return load_mcp_file(default)
        return []
    if isinstance(raw, str):
        path = _safe_component(root, raw)
        if not path.is_file():
            raise PluginError(f"mcpServers path does not exist: {raw}")
        return load_mcp_file(path)
    if isinstance(raw, dict):
        return parse_mcp_map(raw)
    raise PluginError("mcpServers must be a path or an object")


def _safe_component(root: Path, spec: str) -> Path:
    raw = Path(spec)
    if raw.is_absolute() or ".." in raw.parts:
        raise PluginError(f"component path must stay inside the plugin: {spec}")
    candidate = (root / raw).resolve()
    base = root.resolve()
    if candidate != base and base not in candidate.parents:
        raise PluginError(f"component path must stay inside the plugin: {spec}")
    return candidate


def _resource_path(directory: Path, relative_path: str) -> Path:
    if not relative_path or relative_path.strip() != relative_path:
        raise FileNotFoundError(relative_path)
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts or not raw.parts:
        raise FileNotFoundError(relative_path)
    if raw.parts[0] not in _RESOURCE_DIRS:
        raise FileNotFoundError(relative_path)
    root = directory.resolve()
    candidate = (directory / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise FileNotFoundError(relative_path)
    if not candidate.is_file():
        raise FileNotFoundError(relative_path)
    return candidate


def _escapes(root: Path, path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return True
    return resolved != root and root not in resolved.parents


def _explicit_name(data: dict[str, Any]) -> str | None:
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _join_tools(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PluginError(f"{path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PluginError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise PluginError(f"{path}: JSON value must be an object")
    return data
