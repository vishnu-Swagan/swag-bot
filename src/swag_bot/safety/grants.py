"""JSON grant store injected into the plugin installer.

The plugins package must not import this module. The root CLI constructs
``JsonGrantStore`` and passes it to ``configure_grant_store``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from swag_bot.safety.policy import read_grant_maps, write_grant_maps


class JsonGrantStore:
    """Read and write ``$SWAG_HOME/grants.json`` in the safety grant format.

    Active grants live under ``plugins``. Disabled plugins move to
    ``suspended``, which ``load_grants`` does not apply. Nothing here changes
    risk classification: a missing grant stays a hard deny, and ``destructive``
    stays ``destructive``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    def replace(self, plugin: str, permissions: Sequence[str], *, active: bool = True) -> None:
        """Set ``plugin``'s grants to exactly ``permissions``."""
        plugins, suspended = read_grant_maps(self._path)
        recorded = sorted(set(permissions))
        if active:
            plugins[plugin] = recorded
            suspended.pop(plugin, None)
        else:
            plugins.pop(plugin, None)
            suspended[plugin] = recorded
        write_grant_maps(plugins, suspended, self._path)

    def suspend(self, plugin: str) -> None:
        """Move active grants aside so the policy denies this plugin."""
        plugins, suspended = read_grant_maps(self._path)
        if plugin in plugins:
            suspended[plugin] = plugins.pop(plugin)
        write_grant_maps(plugins, suspended, self._path)

    def resume(self, plugin: str) -> None:
        """Apply grants that were suspended. Extra active grants are kept."""
        plugins, suspended = read_grant_maps(self._path)
        if plugin in suspended:
            current = list(plugins.get(plugin, []))
            for permission in suspended.pop(plugin):
                if permission not in current:
                    current.append(permission)
            plugins[plugin] = current
        write_grant_maps(plugins, suspended, self._path)

    def revoke(self, plugin: str) -> None:
        """Drop active and suspended grants for ``plugin``."""
        plugins, suspended = read_grant_maps(self._path)
        plugins.pop(plugin, None)
        suspended.pop(plugin, None)
        write_grant_maps(plugins, suspended, self._path)
