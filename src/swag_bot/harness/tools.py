"""Narrow the tool list a small model sees on each turn.

A 3B model given every tool at once rewrote the same file and never ran it.
The tiny scaffold shows one relevant tool per turn, and after a write it
offers the run tool instead of the write tool again.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from swag_bot.core.scaffold import ToolPicker
from swag_bot.interfaces import Step, Tool

_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("write_file", ("write", "create", "save")),
    ("run_shell", ("run", "execute", "python", "pytest", "shell")),
    ("read_file", ("read", "open", "cat")),
)


def make_picker(*, max_tools: int | None, one_tool_per_turn: bool) -> ToolPicker:
    """Return a picker that keeps the tools most relevant to the step."""

    def pick(
        step: Step,
        tools: Sequence[Tool],
        round_index: int,
        called: set[str],
    ) -> Sequence[Tool]:
        del round_index
        ordered = order_tools(step, tools)
        fresh = [tool for tool in ordered if tool.name not in called]
        if fresh:
            pool = fresh
        else:
            pool = [
                tool
                for tool in ordered
                if tool.name != "write_file" or "write_file" not in called
            ]
            if not pool:
                pool = list(ordered)
        if one_tool_per_turn:
            return pool[:1]
        if max_tools is None:
            return pool
        return pool[:max_tools]

    return pick


def order_tools(step: Step, tools: Sequence[Tool]) -> list[Tool]:
    """Tools mentioned by the step first, in the order the step mentions them."""
    text = f"{step.title}\n{step.instruction}".casefold()
    ranked: list[tuple[int, int, Tool]] = []
    rest: list[Tool] = []
    for index, tool in enumerate(tools):
        position = _mention_at(text, tool.name)
        if position is None:
            rest.append(tool)
        else:
            ranked.append((position, index, tool))
    ranked.sort()
    return [tool for _position, _index, tool in ranked] + rest


def _mention_at(text: str, name: str) -> int | None:
    positions: list[int] = []
    for needle in (name, name.replace("_", " ")):
        match = re.search(rf"\b{re.escape(needle)}\b", text)
        if match is not None:
            positions.append(match.start())
    for tool_name, hints in _HINTS:
        if tool_name != name:
            continue
        for hint in hints:
            match = re.search(rf"\b{re.escape(hint)}\b", text)
            if match is not None:
                positions.append(match.start())
    if not positions:
        return None
    return min(positions)
