"""Terminal approval prompt."""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from swag_bot.interfaces import SWAG_TAINT_KEY, ActionRequest


class RichApprovalPrompter:
    """Show the action in a panel and ask for yes or no. The default is no."""

    def __init__(
        self,
        console: Console | None = None,
        confirm: Callable[..., bool] | None = None,
    ) -> None:
        self.console = console or Console()
        self._confirm = confirm

    def prompt(self, action: ActionRequest) -> bool:
        """Return True to allow the action, False to deny it."""
        self.console.print(_panel(action))
        try:
            if self._confirm is not None:
                return bool(self._confirm("Allow this action?", default=False))
            return bool(Confirm.ask("Allow this action?", console=self.console, default=False))
        except (EOFError, KeyboardInterrupt):
            self.console.print("Denied (no answer).")
            return False


def _panel(action: ActionRequest) -> Panel:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("field", style="bold")
    table.add_column("value")
    table.add_row("kind", action.kind)
    table.add_row("risk", action.risk.value)
    table.add_row("summary", action.summary)
    if action.target:
        table.add_row("target", action.target)
    plugin = action.arguments.get("plugin")
    if isinstance(plugin, str) and plugin:
        table.add_row("plugin", plugin)
    stamp = action.arguments.get(SWAG_TAINT_KEY)
    if isinstance(stamp, dict) and stamp.get("tainted") is True:
        sources = stamp.get("sources")
        if isinstance(sources, list) and sources:
            table.add_row("taint", ", ".join(str(item) for item in sources))
        sinks = stamp.get("sinks")
        if isinstance(sinks, list) and sinks:
            table.add_row("sink", ", ".join(str(item) for item in sinks))
        reason = stamp.get("reason")
        if isinstance(reason, str) and reason.strip():
            table.add_row("why", reason)
    return Panel(table, title="Approval required", border_style="yellow")
