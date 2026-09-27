"""Autonomy, risk classification, and per-plugin permission grants."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from swag_bot.config import swag_home
from swag_bot.errors import SandboxError, SwagError
from swag_bot.interfaces import (
    ActionRequest,
    AutonomyLevel,
    Permission,
    Reversibility,
    RiskLevel,
    default_requires_approval,
    resolve_sandbox_path,
)
from swag_bot.safety.compensation import CompensationRegistry
from swag_bot.safety.reversibility import classify_reversibility

_KNOWN_PERMISSIONS = {item.value for item in Permission}

_WRITE_KINDS = {"write_file", "edit_file", "create_file"}
_READ_KINDS = {"read_file", "list_dir", "memory", "search"}
_DELETE_KINDS = {"delete", "unlink"}
_SHELL_KINDS = {"run_command", "shell", "exec", "bash", "tool", "mcp"}
_NETWORK_KINDS = {"network", "http", "fetch", "send_message", "message", "email"}
_SPEND_KINDS = {"spend", "payment", "purchase", "billing"}

_DELETE_TEXT = re.compile(r"\b(delete|unlink|wipe|rm\s+-[a-z]*f)\b", re.IGNORECASE)
_SPEND_TEXT = re.compile(
    r"\b(spend(?:ing)?\s+money|purchase|payment|credit card|billing)\b",
    re.IGNORECASE,
)
_SEND_TEXT = re.compile(
    r"\b(send(?:ing)?\s+(?:a\s+)?(?:message|email|mail)|post\s+to\s+slack)\b",
    re.IGNORECASE,
)
_NETWORK_TEXT = re.compile(r"\b(https?://|curl|wget)\b", re.IGNORECASE)
_SHELL_TEXT = re.compile(r"\b(shell command|run command|bash|subprocess)\b", re.IGNORECASE)

_KIND_PERMISSION = {
    "read_file": Permission.FILESYSTEM_READ.value,
    "list_dir": Permission.FILESYSTEM_READ.value,
    "memory": Permission.FILESYSTEM_READ.value,
    "search": Permission.FILESYSTEM_READ.value,
    "write_file": Permission.FILESYSTEM_WRITE.value,
    "edit_file": Permission.FILESYSTEM_WRITE.value,
    "create_file": Permission.FILESYSTEM_WRITE.value,
    "delete": Permission.FILESYSTEM_WRITE.value,
    "unlink": Permission.FILESYSTEM_WRITE.value,
    "run_command": Permission.SHELL.value,
    "shell": Permission.SHELL.value,
    "exec": Permission.SHELL.value,
    "bash": Permission.SHELL.value,
    "network": Permission.NETWORK.value,
    "http": Permission.NETWORK.value,
    "fetch": Permission.NETWORK.value,
    "send_message": Permission.NETWORK.value,
    "message": Permission.NETWORK.value,
    "email": Permission.NETWORK.value,
    "tool": Permission.MCP.value,
}

_SEVERITY = {
    RiskLevel.READ: 0,
    RiskLevel.WRITE: 1,
    RiskLevel.EXECUTE: 2,
    RiskLevel.NETWORK: 3,
    RiskLevel.DESTRUCTIVE: 4,
}


class PolicyDecision(StrEnum):
    """What the policy wants done with an action before it runs."""

    ALLOW = "allow"
    PROMPT = "prompt"
    DENY = "deny"


def grants_path() -> Path:
    """Where per-plugin grants are stored for this ``SWAG_HOME``."""
    return swag_home() / "grants.json"


def load_grants(path: Path | None = None) -> dict[str, set[str]]:
    """Read active grants from ``grants.json``. A missing file means no grants.

    Suspended grants (plugins that are installed but disabled) are not
    included. A missing grant is a hard deny and is not lowered here.
    """
    plugins, _suspended = read_grant_maps(path)
    return {name: set(values) for name, values in plugins.items()}


def load_suspended_grants(path: Path | None = None) -> dict[str, set[str]]:
    """Grants remembered for disabled plugins. They are not applied."""
    _plugins, suspended = read_grant_maps(path)
    return {name: set(values) for name, values in suspended.items()}


def read_grant_maps(
    path: Path | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Active ``plugins`` map and the ``suspended`` map.

    A missing file is two empty maps. When ``plugins`` is absent, the file
    itself is the active map (older files). ``suspended`` is ignored by
    ``load_grants``.
    """
    target = grants_path() if path is None else path
    if not target.is_file():
        return {}, {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SwagError(f"cannot read grants {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise SwagError(f"cannot read grants {target}: expected a plugins object")
    if "plugins" in data:
        plugins_raw: object = data["plugins"]
    else:
        plugins_raw = {key: value for key, value in data.items() if key != "suspended"}
    plugins = _permission_map(plugins_raw, target)
    if "suspended" not in data:
        return plugins, {}
    return plugins, _permission_map(data["suspended"], target)


def save_grants(grants: Mapping[str, Sequence[str] | set[str]], path: Path | None = None) -> Path:
    """Write active grants and keep any suspended grants already on disk."""
    target = grants_path() if path is None else path
    suspended: dict[str, list[str]] = {}
    if target.is_file():
        _plugins, suspended = read_grant_maps(target)
    return write_grant_maps(grants, suspended, target)


def write_grant_maps(
    plugins: Mapping[str, Sequence[str] | set[str]],
    suspended: Mapping[str, Sequence[str] | set[str]] | None = None,
    path: Path | None = None,
) -> Path:
    """Write ``grants.json``. Returns the path written.

    ``suspended`` is omitted when empty so a file with only active grants
    stays ``{"plugins": {...}}``.
    """
    target = grants_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, dict[str, list[str]]] = {"plugins": _sorted_grants(plugins)}
    held = _sorted_grants(suspended or {})
    if held:
        payload["suspended"] = held
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def change_grant(
    plugin: str,
    permission: str,
    *,
    add: bool,
    path: Path | None = None,
) -> None:
    """Add or remove one permission without reactivating a suspended plugin."""
    plugins, suspended = read_grant_maps(path)
    bucket = suspended if plugin in suspended and plugin not in plugins else plugins
    current = set(bucket.get(plugin, []))
    if add:
        current.add(permission)
    else:
        current.discard(permission)
    if current:
        bucket[plugin] = sorted(current)
    else:
        bucket.pop(plugin, None)
    write_grant_maps(plugins, suspended, path)


def _permission_map(raw: object, target: Path) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        raise SwagError(f"cannot read grants {target}: expected a plugins object")
    grants: dict[str, list[str]] = {}
    for name, values in raw.items():
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise SwagError(f"grants for {name} must be a list of strings")
        grants[str(name)] = list(values)
    return grants


def _sorted_grants(
    grants: Mapping[str, Sequence[str] | set[str]],
) -> dict[str, list[str]]:
    return {name: sorted(set(values)) for name, values in sorted(grants.items())}


def required_permission(action: ActionRequest) -> str:
    """Capability a plugin must hold to perform ``action``."""
    explicit = action.arguments.get("permission")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return _KIND_PERMISSION.get(action.kind, action.kind)


def _higher(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    return left if _SEVERITY[left] >= _SEVERITY[right] else right


class DefaultPermissionPolicy:
    """Classify actions and decide allow, prompt, or hard deny.

    ``requires_approval`` never prompts less often than
    ``default_requires_approval``. A missing plugin grant is a hard deny
    (``decide`` returns ``deny``) and does not lower that rule.
    ``classify`` never lowers a ``destructive`` risk.
    """

    def __init__(
        self,
        autonomy: AutonomyLevel,
        *,
        grants: Mapping[str, set[str] | Sequence[str]] | None = None,
        workdir: Path | None = None,
        compensations: CompensationRegistry | None = None,
    ) -> None:
        self._autonomy = autonomy
        self._grants: dict[str, set[str]] = {
            name: set(values) for name, values in (grants or {}).items()
        }
        self._workdir = workdir
        self._compensations = compensations

    @property
    def autonomy(self) -> AutonomyLevel:
        return self._autonomy

    @property
    def grants(self) -> dict[str, set[str]]:
        return {name: set(values) for name, values in self._grants.items()}

    def grant(self, plugin: str, permissions: Sequence[str]) -> None:
        """Add permissions for ``plugin``."""
        self._grants.setdefault(plugin, set()).update(permissions)

    def revoke(self, plugin: str, permission: str | None = None) -> None:
        """Drop one permission, or every grant for ``plugin``."""
        if permission is None:
            self._grants.pop(plugin, None)
            return
        current = self._grants.get(plugin)
        if current is None:
            return
        current.discard(permission)
        if not current:
            self._grants.pop(plugin, None)

    def bind_compensations(self, registry: CompensationRegistry) -> None:
        """Use ``registry`` when deciding whether an external action has an inverse."""
        self._compensations = registry

    def classify(self, action: ActionRequest) -> RiskLevel:
        """Risk used for the decision. Never lower than ``destructive``."""
        if action.risk is RiskLevel.DESTRUCTIVE:
            return RiskLevel.DESTRUCTIVE
        return _higher(action.risk, self._infer(action))

    def reversibility(self, action: ActionRequest) -> Reversibility:
        """Whether the undo ledger can restore ``action``.

        ``ask-irreversible`` prompts only when this is ``irreversible``.
        ``ask-risky`` does not use this to skip a prompt.
        """
        return classify_reversibility(
            action,
            compensations=self._compensations,
            workdir=self._workdir,
        )

    def requires_approval(self, action: ActionRequest) -> bool:
        """True when the user must be asked. May be true more often than the default."""
        if self._autonomy is AutonomyLevel.ASK_IRREVERSIBLE:
            return self.reversibility(action) is Reversibility.IRREVERSIBLE
        return default_requires_approval(self.autonomy, self.classify(action))

    def is_denied(self, action: ActionRequest) -> bool:
        """Hard deny when a plugin-scoped action lacks its grant."""
        plugin = _plugin_name(action)
        if plugin is None:
            return False
        needed = required_permission(action)
        return needed not in self._grants.get(plugin, set())

    def decide(self, action: ActionRequest) -> PolicyDecision:
        """Allow, prompt, or deny. A hard deny does not prompt."""
        if self.is_denied(action):
            return PolicyDecision.DENY
        if self.requires_approval(action):
            return PolicyDecision.PROMPT
        return PolicyDecision.ALLOW

    def _infer(self, action: ActionRequest) -> RiskLevel:
        kind = action.kind
        blob = f"{kind}\n{action.summary}".replace("_", " ")
        risk = RiskLevel.READ
        if kind in _READ_KINDS:
            risk = RiskLevel.READ
        if kind in _WRITE_KINDS:
            risk = RiskLevel.WRITE
        if kind in _SHELL_KINDS or _SHELL_TEXT.search(blob):
            risk = _higher(risk, RiskLevel.EXECUTE)
        if kind in _NETWORK_KINDS or _NETWORK_TEXT.search(blob) or _SEND_TEXT.search(blob):
            risk = _higher(risk, RiskLevel.NETWORK)
        destructive = (
            kind in _DELETE_KINDS
            or kind in _SPEND_KINDS
            or _DELETE_TEXT.search(blob)
            or _SPEND_TEXT.search(blob)
        )
        if destructive:
            risk = RiskLevel.DESTRUCTIVE
        if _path_is_outside(action, self._workdir):
            if kind in _WRITE_KINDS or kind in _DELETE_KINDS:
                risk = RiskLevel.DESTRUCTIVE
            else:
                risk = _higher(risk, RiskLevel.WRITE)
        permission = required_permission(action)
        if permission not in _KNOWN_PERMISSIONS:
            risk = _higher(risk, RiskLevel.WRITE)
        return risk


def _plugin_name(action: ActionRequest) -> str | None:
    plugin = action.arguments.get("plugin")
    if isinstance(plugin, str) and plugin.strip():
        return plugin.strip()
    return None


def _path_is_outside(action: ActionRequest, workdir: Path | None) -> bool:
    raw = action.target
    if raw is None:
        candidate = action.arguments.get("path")
        raw = candidate if isinstance(candidate, str) else None
    if not raw:
        return False
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        return True
    root = workdir
    arg_root = action.arguments.get("workdir")
    if isinstance(arg_root, str) and arg_root.strip():
        root = Path(arg_root)
    if root is None:
        return False
    try:
        resolve_sandbox_path(root, raw)
    except SandboxError:
        return True
    return False
