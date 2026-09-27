"""Inverses for side effects a workspace snapshot cannot restore.

Plugins declare them in ``plugin.json`` under ``compensations``. MCP tools
can declare the same object in the tool annotation ``swagCompensation``.
A declaration names the inverse. A callable registered in this process, or
an ``entrypoint`` of ``module:function``, is what actually runs on undo.

Without a callable, undo reports the inverse instead of pretending it ran.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from swag_bot.errors import SwagError


class CompensationSpec(BaseModel):
    """One registered inverse. ``tool`` is the action that needs undoing."""

    tool: str
    inverse: str
    description: str = ""
    argument_map: dict[str, str] = Field(default_factory=dict)
    entrypoint: str | None = None
    source: str = ""


class CompensationCall(BaseModel):
    """What an inverse handler receives. ``resolved`` follows ``argument_map``."""

    tool: str
    inverse: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    argument_map: dict[str, str] = Field(default_factory=dict)
    resolved: dict[str, Any] = Field(default_factory=dict)


CompensationHandler = Callable[[CompensationCall], str]


class CompensationRegistry:
    """Specs and the callables that perform them."""

    def __init__(self) -> None:
        self._specs: dict[str, CompensationSpec] = {}
        self._handlers: dict[str, CompensationHandler] = {}

    def register(self, spec: CompensationSpec, handler: CompensationHandler | None = None) -> None:
        """Remember ``spec``. ``handler`` is what undo calls for ``spec.tool``."""
        if not spec.tool.strip() or not spec.inverse.strip():
            raise SwagError("a compensation needs a tool name and an inverse")
        self._specs[spec.tool] = spec
        if handler is not None:
            self._handlers[spec.tool] = handler
        elif spec.entrypoint:
            loaded = load_entrypoint(spec.entrypoint)
            if loaded is not None:
                self._handlers[spec.tool] = loaded

    def load_entries(self, entries: Sequence[Mapping[str, Any]], *, source: str = "") -> None:
        """Add declarations from a manifest or a tool annotation.

        An entry that is missing ``tool`` or ``inverse`` is skipped. A spec
        that already has a handler is left in place so a later manifest load
        does not drop a callable registered in this process.
        """
        for raw in entries:
            spec = spec_from_mapping(raw, source=source)
            if spec is None:
                continue
            if spec.tool in self._handlers:
                continue
            self.register(spec)

    def lookup(self, tool: str) -> CompensationSpec | None:
        """The spec for ``tool``, or None."""
        return self._specs.get(tool)

    def has_handler(self, tool: str) -> bool:
        """True when undo can run an inverse for ``tool`` in this process."""
        if tool in self._handlers:
            return True
        spec = self._specs.get(tool)
        return bool(spec and spec.entrypoint)

    def run(self, call: CompensationCall) -> tuple[bool, str]:
        """Run the inverse. ``(False, reason)`` means it did not run."""
        handler = self._handlers.get(call.tool)
        if handler is None:
            spec = self._specs.get(call.tool)
            if spec is not None and spec.entrypoint:
                loaded = load_entrypoint(spec.entrypoint)
                if loaded is None:
                    return False, f"could not import {spec.entrypoint}"
                self._handlers[call.tool] = loaded
                handler = loaded
        if handler is None:
            inverse = call.inverse or call.tool
            return False, f"no handler registered for {inverse}"
        try:
            result = handler(call)
        except Exception as exc:
            return False, f"{call.inverse} failed: {exc}"
        return True, result


def spec_from_mapping(raw: Mapping[str, Any], *, source: str = "") -> CompensationSpec | None:
    """Build a spec from a manifest object. Return None when it is incomplete."""
    tool = raw.get("tool") or raw.get("name")
    inverse = raw.get("inverse") or raw.get("inverse_tool") or raw.get("compensate")
    if not isinstance(tool, str) or not tool.strip():
        return None
    if not isinstance(inverse, str) or not inverse.strip():
        return None
    argument_map = raw.get("argument_map")
    if argument_map is None:
        argument_map = raw.get("argumentMap") or {}
    if not isinstance(argument_map, dict):
        return None
    mapped: dict[str, str] = {}
    for key, value in argument_map.items():
        if isinstance(key, str) and isinstance(value, str):
            mapped[key] = value
    description = raw.get("description")
    entrypoint = raw.get("entrypoint")
    return CompensationSpec(
        tool=tool.strip(),
        inverse=inverse.strip(),
        description=description if isinstance(description, str) else "",
        argument_map=mapped,
        entrypoint=entrypoint.strip()
        if isinstance(entrypoint, str) and entrypoint.strip()
        else None,
        source=source,
    )


def resolve_arguments(
    argument_map: Mapping[str, str],
    arguments: Mapping[str, Any],
    outcome: str | None,
) -> dict[str, Any]:
    """Map stored tool arguments onto the inverse's arguments.

    An empty map passes the original arguments through. ``outcome`` as a
    source uses the tool's recorded result. ``arguments.name`` and ``name``
    both read that argument.
    """
    if not argument_map:
        return dict(arguments)
    resolved: dict[str, Any] = {}
    for dest, source in argument_map.items():
        if source == "outcome":
            resolved[dest] = outcome
        elif source.startswith("arguments."):
            resolved[dest] = arguments.get(source.split(".", 1)[1])
        else:
            resolved[dest] = arguments.get(source)
    return resolved


def load_entrypoint(entrypoint: str) -> CompensationHandler | None:
    """Import ``module:function``. The function receives the resolved dict.

    Returns None when the module cannot be imported. The caller reports that
    instead of failing the whole undo.
    """
    if ":" not in entrypoint:
        return None
    module_name, func_name = entrypoint.split(":", 1)
    if not module_name or not func_name:
        return None
    try:
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
    except (ImportError, AttributeError):
        return None
    if not callable(func):
        return None

    def handler(call: CompensationCall) -> str:
        result = func(call.resolved)
        return "" if result is None else str(result)

    return handler
