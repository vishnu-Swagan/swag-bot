"""Read a Claude Code marketplace (``.claude-plugin/marketplace.json``).

A marketplace is a catalog. This module parses it and resolves a plugin
entry to a local directory. GitHub and git URL entries are cloned by the
caller-supplied ``clone`` function. npm and pip sources are recognized and
refused. Nothing from a marketplace is executed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from swag_bot.interfaces import PluginAuthor, PluginManifest
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.loader import LoadedPlugin, load_plugin

CloneFn = Callable[[str, Path, str | None], None]


class MarketplacePlugin(BaseModel):
    """One ``plugins[]`` entry. Unknown keys are kept so Claude fields still load."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    source: str | dict[str, Any]
    description: str | None = None
    version: str | None = None
    author: PluginAuthor | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: list[str] = Field(default_factory=list)
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    strict: bool = True
    default_enabled: bool | None = Field(default=None, alias="defaultEnabled")
    skills: str | list[str] | None = None
    commands: str | list[str] | None = None
    agents: str | list[str] | None = None
    mcp_servers: str | dict[str, Any] | None = Field(default=None, alias="mcpServers")
    permissions: list[str] = Field(default_factory=list)

    @field_validator("author", mode="before")
    @classmethod
    def _author(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("marketplace plugin name must be non-empty and contain no spaces")
        return value

    @field_validator("source", mode="before")
    @classmethod
    def _source(cls, value: Any) -> Any:
        if isinstance(value, str) or isinstance(value, dict):
            return value
        raise ValueError("plugin source must be a path or an object")


class Marketplace(BaseModel):
    """``.claude-plugin/marketplace.json``."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    owner: PluginAuthor
    plugins: list[MarketplacePlugin]
    description: str | None = None
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("owner", mode="before")
    @classmethod
    def _owner(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("marketplace name must be non-empty and contain no spaces")
        return value

    @model_validator(mode="after")
    def _unique_plugins(self) -> Marketplace:
        names = [plugin.name for plugin in self.plugins]
        if len(names) != len(set(names)):
            raise ValueError("marketplace plugin names must be unique")
        return self

    @property
    def plugin_root(self) -> str | None:
        """``metadata.pluginRoot``, prepended to relative sources that omit ``./``."""
        raw = self.metadata.get("pluginRoot") if isinstance(self.metadata, dict) else None
        return raw if isinstance(raw, str) and raw else None


def load_marketplace(root: Path) -> Marketplace:
    """Parse ``root/.claude-plugin/marketplace.json``."""
    path = root.expanduser().resolve() / ".claude-plugin" / "marketplace.json"
    if not path.is_file():
        raise PluginError(f"no marketplace manifest at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PluginError(f"{path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PluginError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise PluginError(f"{path}: marketplace JSON must be an object")
    try:
        return Marketplace.model_validate(data)
    except ValidationError as exc:
        raise PluginError(f"{path}: invalid marketplace: {exc}") from exc


def select_entry(marketplace: Marketplace, plugin_name: str | None) -> MarketplacePlugin:
    """Pick one plugin. A marketplace with a single entry does not need a name."""
    if not marketplace.plugins:
        raise PluginError(f"marketplace {marketplace.name!r} lists no plugins")
    if plugin_name is None:
        if len(marketplace.plugins) == 1:
            return marketplace.plugins[0]
        listed = ", ".join(plugin.name for plugin in marketplace.plugins)
        raise PluginError(
            f"marketplace {marketplace.name!r} has more than one plugin ({listed}); "
            "pass the plugin name"
        )
    for plugin in marketplace.plugins:
        if plugin.name == plugin_name:
            return plugin
    raise PluginError(f"marketplace {marketplace.name!r} has no plugin {plugin_name!r}")


def resolve_marketplace_plugin(
    marketplace_root: Path,
    marketplace: Marketplace,
    entry: MarketplacePlugin,
    clone: CloneFn | None = None,
    *,
    workdir: Path | None = None,
) -> LoadedPlugin:
    """Resolve ``entry`` to a loaded plugin. ``clone`` fetches git sources into ``workdir``."""
    directory = resolve_source_directory(
        marketplace_root,
        marketplace,
        entry,
        clone,
        workdir=workdir,
    )
    return load_entry_plugin(directory, entry)


def load_entry_plugin(directory: Path, entry: MarketplacePlugin) -> LoadedPlugin:
    """Load ``plugin.json``, or synthesize a manifest when ``strict`` is false."""
    manifest_path = directory / ".claude-plugin" / "plugin.json"
    if manifest_path.is_file():
        plugin = load_plugin(directory)
        if plugin.manifest.name != entry.name:
            raise PluginError(
                f"marketplace plugin {entry.name!r} does not match "
                f"plugin.json name {plugin.manifest.name!r}"
            )
        return plugin
    if entry.strict:
        raise PluginError(
            f"marketplace plugin {entry.name!r} is missing .claude-plugin/plugin.json"
        )
    try:
        manifest = PluginManifest.from_plugin_json(_synthetic_manifest(entry))
    except ValidationError as exc:
        raise PluginError(
            f"marketplace plugin {entry.name!r} has an invalid manifest: {exc}"
        ) from exc
    return load_plugin(directory, manifest=manifest)


def resolve_source_directory(
    marketplace_root: Path,
    marketplace: Marketplace,
    entry: MarketplacePlugin,
    clone: CloneFn | None = None,
    *,
    workdir: Path | None = None,
) -> Path:
    """Return the local directory for a marketplace plugin source."""
    source = entry.source
    if isinstance(source, str):
        return _relative_directory(marketplace_root, marketplace.plugin_root, source)
    kind = source.get("source")
    if kind == "github":
        repo = source.get("repo")
        if not isinstance(repo, str) or repo.count("/") != 1 or not repo.split("/")[0]:
            raise PluginError(f"plugin {entry.name!r} github source needs owner/repo")
        ref = source.get("ref")
        return _clone_repository(
            clone,
            f"https://github.com/{repo}.git",
            ref if isinstance(ref, str) else None,
            workdir,
        )
    if kind == "url":
        url = source.get("url")
        if not isinstance(url, str) or not url:
            raise PluginError(f"plugin {entry.name!r} url source needs a url")
        ref = source.get("ref")
        return _clone_repository(clone, url, ref if isinstance(ref, str) else None, workdir)
    if kind == "git-subdir":
        url = source.get("url")
        subpath = source.get("path")
        if not isinstance(url, str) or not url or not isinstance(subpath, str) or not subpath:
            raise PluginError(f"plugin {entry.name!r} git-subdir source needs url and path")
        ref = source.get("ref")
        repo = _clone_repository(clone, url, ref if isinstance(ref, str) else None, workdir)
        relative = subpath if subpath.startswith("./") else f"./{subpath}"
        return _relative_directory(repo, None, relative)
    if kind in {"npm", "pip"}:
        raise PluginError(f"{kind} plugin sources are not installed by this version of Swag Bot")
    raise PluginError(f"plugin {entry.name!r} has unsupported source type {kind!r}")


def _synthetic_manifest(entry: MarketplacePlugin) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": entry.name, "permissions": list(entry.permissions)}
    if entry.description is not None:
        payload["description"] = entry.description
    if entry.version is not None:
        payload["version"] = entry.version
    if entry.author is not None:
        payload["author"] = entry.author.model_dump(exclude_none=True)
    if entry.homepage is not None:
        payload["homepage"] = entry.homepage
    if entry.repository is not None:
        payload["repository"] = entry.repository
    if entry.license is not None:
        payload["license"] = entry.license
    if entry.keywords:
        payload["keywords"] = list(entry.keywords)
    if entry.default_enabled is not None:
        payload["defaultEnabled"] = entry.default_enabled
    if entry.skills is not None:
        payload["skills"] = entry.skills
    if entry.commands is not None:
        payload["commands"] = entry.commands
    if entry.agents is not None:
        payload["agents"] = entry.agents
    if entry.mcp_servers is not None:
        payload["mcpServers"] = entry.mcp_servers
    return payload


def _relative_directory(root: Path, plugin_root: str | None, source: str) -> Path:
    if source.startswith("./") or source.startswith("../"):
        relative = source
        base = root
    elif plugin_root:
        relative = str(Path(plugin_root) / source)
        base = root
    else:
        relative = f"./{source}"
        base = root
    path = _safe_directory(base, relative)
    if not path.is_dir():
        raise PluginError(f"marketplace plugin source does not exist: {source}")
    return path


def _safe_directory(root: Path, relative: str) -> Path:
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        raise PluginError(f"marketplace plugin source escapes the marketplace: {relative}")
    candidate = (root / raw).resolve()
    base = root.resolve()
    if candidate != base and base not in candidate.parents:
        raise PluginError(f"marketplace plugin source escapes the marketplace: {relative}")
    return candidate


def _clone_repository(
    clone: CloneFn | None,
    url: str,
    ref: str | None,
    workdir: Path | None,
) -> Path:
    if clone is None:
        raise PluginError(
            "git plugin sources need a clone function; install from a local path "
            "or pass a git client"
        )
    if workdir is None:
        raise PluginError("git plugin sources need a working directory")
    dest = workdir / f"clone-{uuid4().hex[:8]}"
    clone(url, dest, ref)
    if not dest.is_dir():
        raise PluginError("git clone did not create a repository directory")
    return dest
