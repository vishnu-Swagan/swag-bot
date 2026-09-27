"""In-memory registry of plugins, skills, commands, agents, and MCP specs.

``discover_plugins`` reads ``settings.plugin_dirs`` and enabled installs under
the Swag home. Standalone skills come from ``.agents/skills`` and
``$SWAG_HOME/skills``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from swag_bot.config import Settings, swag_home
from swag_bot.interfaces import (
    AgentDefinition,
    MCPServerSpec,
    Plugin,
    Skill,
    SkillMeta,
    SlashCommand,
)
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.installer import installed_plugin_dir, list_installed
from swag_bot.plugins.loader import (
    FileSkill,
    LoadedPlugin,
    discover_skill_directories,
    load_plugin,
    load_skill_directory,
    plugins_from_path,
    substitute_arguments,
)
from swag_bot.plugins.selector import select_skills


class PluginRegistry:
    """Loaded plugins plus standalone skills. Satisfies ``interfaces.PluginRegistry``."""

    def __init__(
        self,
        plugins: Sequence[Plugin],
        extra_skills: Sequence[Skill] | None = None,
    ) -> None:
        self._plugins = list(plugins)
        self._extra = list(extra_skills or [])

    def list_plugins(self) -> list[Plugin]:
        return list(self._plugins)

    def list_skills(self) -> list[SkillMeta]:
        metas: list[SkillMeta] = []
        seen: set[str] = set()
        for plugin in self._plugins:
            for meta in plugin.list_skills():
                if meta.name in seen:
                    continue
                seen.add(meta.name)
                metas.append(meta)
        for skill in self._extra:
            if skill.meta.name in seen:
                continue
            seen.add(skill.meta.name)
            metas.append(skill.meta)
        return metas

    def load_skill(self, name: str) -> Skill:
        for plugin in self._plugins:
            try:
                return plugin.load_skill(name)
            except KeyError:
                continue
        for skill in self._extra:
            if skill.meta.name == name:
                return skill
        raise KeyError(name)

    def list_commands(self) -> list[SlashCommand]:
        commands: list[SlashCommand] = []
        seen: set[str] = set()
        for plugin in self._plugins:
            for command in plugin.list_commands():
                if command.name in seen:
                    continue
                seen.add(command.name)
                commands.append(command)
        return commands

    def load_command(self, name: str, arguments: str = "") -> SlashCommand:
        for plugin in self._plugins:
            command = _take_named(plugin, "load_command", "list_commands", name)
            if command is not None and isinstance(command, SlashCommand):
                return command.model_copy(
                    update={"body": substitute_arguments(command.body, arguments)}
                )
        raise KeyError(name)

    def list_agents(self) -> list[AgentDefinition]:
        agents: list[AgentDefinition] = []
        seen: set[str] = set()
        for plugin in self._plugins:
            lister = getattr(plugin, "list_agents", None)
            if not callable(lister):
                continue
            for agent in lister():
                if not isinstance(agent, AgentDefinition) or agent.name in seen:
                    continue
                seen.add(agent.name)
                agents.append(agent)
        return agents

    def load_agent(self, name: str) -> AgentDefinition:
        for plugin in self._plugins:
            agent = _take_named(plugin, "load_agent", "list_agents", name)
            if isinstance(agent, AgentDefinition):
                return agent
        raise KeyError(name)

    def list_mcp_servers(self) -> list[MCPServerSpec]:
        servers: list[MCPServerSpec] = []
        seen: set[str] = set()
        for plugin in self._plugins:
            lister = getattr(plugin, "list_mcp_servers", None)
            if not callable(lister):
                continue
            for spec in lister():
                if not isinstance(spec, MCPServerSpec) or spec.name in seen:
                    continue
                seen.add(spec.name)
                servers.append(spec)
        return servers

    def select_skills(self, goal: str, *, limit: int = 5) -> list[SkillMeta]:
        return select_skills(self.list_skills(), goal, limit=limit)


def discover_plugins(settings: Settings, *, home: Path | None = None) -> list[Plugin]:
    """Enabled plugins from ``settings.plugin_dirs``, then enabled installs.

    A name that already appeared in ``plugin_dirs`` is kept. That lets a
    checkout you are editing win over the copy under the Swag home.
    """
    home_dir = _home(home)
    found: list[Plugin] = []
    seen: set[str] = set()

    def add(plugin: LoadedPlugin) -> None:
        if plugin.manifest.name in seen:
            return
        seen.add(plugin.manifest.name)
        found.append(plugin)

    for entry in settings.plugin_dirs:
        for plugin in plugins_from_path(Path(entry).expanduser()):
            add(plugin)
    for record in list_installed(home=home_dir):
        if not record.enabled:
            continue
        directory = installed_plugin_dir(home_dir, record.name)
        manifest = directory / ".claude-plugin" / "plugin.json"
        if manifest.is_file():
            add(load_plugin(directory))
    return found


def discover_standalone_skills(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[FileSkill]:
    """Skills in ``.agents/skills`` (under ``cwd``) and ``$SWAG_HOME/skills``."""
    skills: list[FileSkill] = []
    seen: set[str] = set()
    for root in standalone_skill_roots(cwd=cwd, home=home):
        for directory in discover_skill_directories(root):
            skill = load_skill_directory(directory)
            if skill.meta.name in seen:
                continue
            seen.add(skill.meta.name)
            skills.append(skill)
    return skills


def standalone_skill_roots(*, cwd: Path | None = None, home: Path | None = None) -> list[Path]:
    """Directories searched for standalone skills. Missing directories are included."""
    project = (cwd if cwd is not None else Path.cwd()) / ".agents" / "skills"
    user = _home(home) / "skills"
    return [project, user]


def build_registry(
    settings: Settings,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> PluginRegistry:
    """Plugins from discovery plus standalone skills."""
    plugins = discover_plugins(settings, home=home)
    skills = discover_standalone_skills(cwd=cwd, home=home)
    return PluginRegistry(plugins, skills)


def find_plugin(name: str, settings: Settings, *, home: Path | None = None) -> LoadedPlugin:
    """An installed plugin (enabled or not), else one discovered from ``plugin_dirs``."""
    home_dir = _home(home)
    for record in list_installed(home=home_dir):
        if record.name != name:
            continue
        directory = installed_plugin_dir(home_dir, name)
        manifest = directory / ".claude-plugin" / "plugin.json"
        if not manifest.is_file():
            raise PluginError(f"installed plugin files are missing: {name}")
        return load_plugin(directory)
    for plugin in discover_plugins(settings, home=home_dir):
        if isinstance(plugin, LoadedPlugin) and plugin.manifest.name == name:
            return plugin
    raise PluginError(f"plugin not found: {name}")


def _home(home: Path | None) -> Path:
    return (home if home is not None else swag_home()).expanduser()


def _take_named(plugin: Plugin, loader_name: str, list_name: str, name: str) -> object | None:
    loader = getattr(plugin, loader_name, None)
    if callable(loader):
        try:
            return loader(name)
        except KeyError:
            return None
    lister = getattr(plugin, list_name, None)
    if not callable(lister):
        return None
    for item in lister():
        if getattr(item, "name", None) == name:
            return item
    return None
