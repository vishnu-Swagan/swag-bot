"""Install, enable, disable, and remove plugins under ``$SWAG_HOME/plugins``.

The registry file is ``$SWAG_HOME/plugins/registry.json``. Each plugin is
copied to ``$SWAG_HOME/plugins/<name>/``. Git sources are cloned with ``git``;
this module does not import a git library.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from swag_bot.config import swag_home
from swag_bot.interfaces import (
    ActionRequest,
    ApprovalPrompter,
    Permission,
    PluginManifest,
    RiskLevel,
)
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.loader import LoadedPlugin, load_plugin
from swag_bot.plugins.marketplace import (
    CloneFn,
    load_marketplace,
    resolve_marketplace_plugin,
    select_entry,
)

_REGISTRY_NAME = "registry.json"
_RESERVED_NAMES = {_REGISTRY_NAME, ".", ".."}
_URL_SECRET = re.compile(r"(://[^/\s:]+:)[^@\s]+@")
_GITHUB = re.compile(
    r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9_.-]*)/(?P<repo>[A-Za-z0-9_.-]+?)(?:@(?P<ref>\S+))?$"
)
_KNOWN_PERMISSIONS = {item.value for item in Permission}
_RISK_RANK = {
    RiskLevel.READ: 0,
    RiskLevel.WRITE: 1,
    RiskLevel.NETWORK: 2,
    RiskLevel.EXECUTE: 3,
    RiskLevel.DESTRUCTIVE: 4,
}

Announce = Callable[[ActionRequest], None]


class InstallRecord(BaseModel):
    """One row in the on-disk plugin registry."""

    name: str
    version: str | None = None
    enabled: bool = True
    source: str
    permissions: list[str] = Field(default_factory=list)
    installed_at: str


class GitSource:
    """A repository to clone. ``ref`` is a branch or tag."""

    def __init__(self, url: str, ref: str | None = None) -> None:
        self.url = url
        self.ref = ref


class LocalSource:
    """A directory on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path


def parse_install_source(spec: str) -> GitSource | LocalSource:
    """Classify ``path``, a git URL, or ``owner/repo[@ref]``."""
    text = spec.strip()
    if not text:
        raise PluginError("install source is empty")
    git_prefix = text.startswith(("https://", "http://", "ssh://", "git://", "git@"))
    if git_prefix or text.endswith(".git"):
        return GitSource(text)
    path = Path(text).expanduser()
    if path.exists() or text.startswith(("/", "./", "../", "~")):
        return LocalSource(path)
    match = _GITHUB.fullmatch(text)
    if match is not None:
        owner = match.group("owner")
        repo = match.group("repo")
        if repo.endswith(".git"):
            repo = repo[: -len(".git")]
        return GitSource(f"https://github.com/{owner}/{repo}.git", match.group("ref"))
    return LocalSource(path)


def install_plugin(
    source: str,
    *,
    prompter: ApprovalPrompter | None = None,
    assume_yes: bool = False,
    plugin_name: str | None = None,
    home: Path | None = None,
    clone: CloneFn | None = None,
    announce: Announce | None = None,
) -> InstallRecord:
    """Copy a plugin into the Swag home and record it.

    Unless ``assume_yes`` is true, ``prompter`` must allow the install.
    The action passed to the prompter lists the requested permissions.
    A denial raises ``PluginError`` and does not write the plugin.
    """
    home_dir = _home(home)
    cloner = clone if clone is not None else default_clone
    with tempfile.TemporaryDirectory(prefix="swag-plugin-src-") as tmp:
        workdir = Path(tmp)
        materialized = _materialize(parse_install_source(source), workdir, cloner)
        plugin, enabled_override = _plugin_from_root(materialized, plugin_name, cloner, workdir)
        action = install_action(plugin.manifest)
        if assume_yes:
            if announce is not None:
                announce(action)
        else:
            if prompter is None:
                raise PluginError("installation requires a prompter or --yes")
            if not prompter.prompt(action):
                raise PluginError("installation denied")
        enabled = plugin.manifest.default_enabled if enabled_override is None else enabled_override
        destination = installed_plugin_dir(home_dir, plugin.manifest.name)
        _install_tree(plugin.root, destination)
    record = InstallRecord(
        name=plugin.manifest.name,
        version=plugin.manifest.version,
        enabled=enabled,
        source=source,
        permissions=list(plugin.manifest.permissions),
        installed_at=datetime.now(UTC).isoformat(),
    )
    _upsert(home_dir, record)
    return record


def list_installed(*, home: Path | None = None) -> list[InstallRecord]:
    """Registry rows. A missing registry is an empty install, not an error."""
    return _read(_home(home))


def set_enabled(name: str, enabled: bool, *, home: Path | None = None) -> InstallRecord:
    """Flip the enabled flag. Raise ``PluginError`` if ``name`` is not installed."""
    home_dir = _home(home)
    records = _read(home_dir)
    for index, record in enumerate(records):
        if record.name == name:
            updated = record.model_copy(update={"enabled": enabled})
            records[index] = updated
            _write(home_dir, records)
            return updated
    raise PluginError(f"plugin is not installed: {name}")


def remove_plugin(name: str, *, home: Path | None = None) -> None:
    """Delete the copied plugin and its registry row."""
    home_dir = _home(home)
    records = _read(home_dir)
    kept = [record for record in records if record.name != name]
    if len(kept) == len(records):
        raise PluginError(f"plugin is not installed: {name}")
    directory = installed_plugin_dir(home_dir, name)
    if directory.exists():
        shutil.rmtree(directory)
    _write(home_dir, kept)


def installed_plugin_dir(home: Path, name: str) -> Path:
    """Directory for an installed plugin. Rejects names that collide with the registry."""
    if name in _RESERVED_NAMES or any(ch in name for ch in "/\\"):
        raise PluginError(f"plugin name cannot be installed: {name}")
    return home / "plugins" / name


def registry_path(home: Path) -> Path:
    """Path of ``registry.json`` for this Swag home."""
    return home / "plugins" / _REGISTRY_NAME


def install_action(manifest: PluginManifest) -> ActionRequest:
    """The approval request shown before a plugin is copied."""
    permissions = list(manifest.permissions)
    shown = ", ".join(permissions) if permissions else "(none)"
    version = f" {manifest.version}" if manifest.version else ""
    return ActionRequest(
        kind="plugin_install",
        summary=f"Install plugin '{manifest.name}'{version} requesting permissions: {shown}",
        risk=install_risk(permissions),
        target=manifest.name,
        arguments={
            "permissions": permissions,
            "version": manifest.version or "",
            "description": manifest.description or "",
        },
    )


def install_risk(permissions: list[str]) -> RiskLevel:
    """Risk shown on the install prompt. Installing always writes, so the floor is write."""
    level = RiskLevel.WRITE
    for name in permissions:
        if name not in _KNOWN_PERMISSIONS:
            candidate = RiskLevel.EXECUTE
        elif name == Permission.SECRETS.value:
            candidate = RiskLevel.DESTRUCTIVE
        elif name == Permission.SHELL.value:
            candidate = RiskLevel.EXECUTE
        elif name in {Permission.NETWORK.value, Permission.MCP.value}:
            candidate = RiskLevel.NETWORK
        elif name == Permission.FILESYSTEM_WRITE.value:
            candidate = RiskLevel.WRITE
        else:
            candidate = RiskLevel.READ
        if _RISK_RANK[candidate] > _RISK_RANK[level]:
            level = candidate
    return level


def default_clone(url: str, dest: Path, ref: str | None) -> None:
    """Shallow-clone ``url`` into ``dest``. ``dest`` must not already exist."""
    command = ["git", "clone", "--depth", "1"]
    if ref:
        command.extend(["--branch", ref])
    command.extend(["--", url, str(dest)])
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = redact_secrets(completed.stderr.strip() or completed.stdout.strip())
        raise PluginError(f"could not clone repository: {detail}")


def redact_secrets(text: str) -> str:
    """Hide userinfo passwords that a git URL may have echoed back."""
    return _URL_SECRET.sub(r"\1***@", text)


def _install_tree(src: Path, dest: Path) -> None:
    """Copy into a staging directory, then swap it into ``dest``."""
    staging = dest.with_name(f"{dest.name}.installing")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        copy_plugin_tree(src, staging)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    if dest.exists():
        shutil.rmtree(dest)
    os.replace(staging, dest)


def copy_plugin_tree(src: Path, dest: Path) -> None:
    """Copy a plugin. Symlinks that leave the plugin root are rejected."""
    source = src.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            continue
        if path.is_symlink():
            resolved = path.resolve()
            if resolved != source and source not in resolved.parents:
                raise PluginError(f"symlink escapes the plugin: {relative.as_posix()}")
        target = dest / relative
        if path.is_dir() and not path.is_symlink():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target, follow_symlinks=True)


def _plugin_from_root(
    root: Path,
    plugin_name: str | None,
    clone: CloneFn,
    workdir: Path,
) -> tuple[LoadedPlugin, bool | None]:
    has_plugin = (root / ".claude-plugin" / "plugin.json").is_file()
    has_market = (root / ".claude-plugin" / "marketplace.json").is_file()
    if has_market and (plugin_name is not None or not has_plugin):
        marketplace = load_marketplace(root)
        entry = select_entry(marketplace, plugin_name)
        plugin = resolve_marketplace_plugin(root, marketplace, entry, clone, workdir=workdir)
        return plugin, entry.default_enabled
    if has_plugin:
        plugin = load_plugin(root)
        if plugin_name is not None and plugin.manifest.name != plugin_name:
            raise PluginError(
                f"plugin.json name is {plugin.manifest.name!r}, not {plugin_name!r}"
            )
        return plugin, None
    raise PluginError(f"no .claude-plugin/plugin.json or marketplace.json in {root}")


def _materialize(source: GitSource | LocalSource, tmp: Path, clone: CloneFn) -> Path:
    if isinstance(source, LocalSource):
        if not source.path.exists():
            raise PluginError(f"path does not exist: {source.path}")
        if not source.path.is_dir():
            raise PluginError(f"plugin source is not a directory: {source.path}")
        return source.path.resolve()
    dest = tmp / "repo"
    clone(source.url, dest, source.ref)
    if not dest.is_dir():
        raise PluginError("git clone did not create a repository directory")
    return dest


def _home(home: Path | None) -> Path:
    return (home if home is not None else swag_home()).expanduser()


def _upsert(home: Path, record: InstallRecord) -> None:
    records = [item for item in _read(home) if item.name != record.name]
    records.append(record)
    records.sort(key=lambda item: item.name)
    _write(home, records)


def _read(home: Path) -> list[InstallRecord]:
    path = registry_path(home)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PluginError(f"cannot read plugin registry {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise PluginError(f"cannot read plugin registry {path}: expected a plugins list")
    records: list[InstallRecord] = []
    for item in data["plugins"]:
        if not isinstance(item, dict):
            raise PluginError(
                f"cannot read plugin registry {path}: a plugin entry is not an object"
            )
        records.append(InstallRecord.model_validate(item))
    return records


def _write(home: Path, records: list[InstallRecord]) -> None:
    path = registry_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "plugins": [record.model_dump(mode="json") for record in records],
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
