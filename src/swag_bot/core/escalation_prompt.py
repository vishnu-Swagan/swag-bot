"""Clarification and jury panels.

The layout matches the taint firewall's approval card (draft PR #11): a yellow
panel, a two-column table, and a default that does not proceed. Taint puts the
source and the reason on the card, then asks "Allow this action?" with the
default no. This module puts the signals and the question on the card, then
asks for an answer whose default is empty. An empty answer, or end of input,
stops the step. The agent does not guess.

A jury rejection is the same card with the title "Blocked by jury" and no
question. The action has already been refused. There is no override prompt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from swag_bot.core.jury import JuryVerdict
from swag_bot.core.uncertainty import Signal
from swag_bot.interfaces import ActionRequest


@dataclass(frozen=True)
class ClarificationRequest:
    """What the user is shown before an uncertain step continues."""

    step_id: str
    step_title: str
    question: str
    uncertainty: float
    confidence: float
    signals: Sequence[Signal]


@runtime_checkable
class EscalationPrompter(Protocol):
    """Asks a clarifying question, and shows a jury block."""

    def ask(self, request: ClarificationRequest) -> str | None:
        """Return the user's answer, or None when they did not give one."""
        ...

    def show_block(self, action: ActionRequest, verdict: JuryVerdict) -> None:
        """Show why an irreversible action was not run."""
        ...


class RichEscalationPrompter:
    """Terminal card for a clarifying question or a jury block."""

    def __init__(
        self,
        console: Console | None = None,
        ask: Callable[[str], str] | None = None,
    ) -> None:
        self.console = console or Console()
        self._ask = ask

    def ask(self, request: ClarificationRequest) -> str | None:
        """Print the card and read one line. Empty input does not guess."""
        self.console.print(_clarification_panel(request))
        try:
            if self._ask is not None:
                raw = self._ask("Your answer")
            else:
                raw = Prompt.ask("Your answer", console=self.console, default="")
        except (EOFError, KeyboardInterrupt):
            self.console.print("Stopped (no answer). The agent will not guess.")
            return None
        text = str(raw).strip()
        if not text:
            self.console.print("Stopped (no answer). The agent will not guess.")
            return None
        return text

    def show_block(self, action: ActionRequest, verdict: JuryVerdict) -> None:
        """Print the block card. Does not ask for an override."""
        self.console.print(_block_panel(action, verdict))


def _clarification_panel(request: ClarificationRequest) -> Panel:
    table = _table()
    table.add_row("step", f"{request.step_id} {request.step_title}".strip())
    table.add_row("uncertainty", f"{request.uncertainty:.2f}")
    table.add_row("confidence", f"{request.confidence:.2f}")
    names = ", ".join(signal.name for signal in request.signals)
    if names:
        table.add_row("signals", names)
    table.add_row("question", request.question)
    return Panel(table, title="Clarification needed", border_style="yellow")


def _block_panel(action: ActionRequest, verdict: JuryVerdict) -> Panel:
    table = _table()
    table.add_row("kind", action.kind)
    table.add_row("risk", action.risk.value)
    table.add_row("summary", action.summary)
    if action.target:
        table.add_row("target", action.target)
    table.add_row("reversibility", verdict.reversibility)
    table.add_row("jury", verdict.independence)
    if verdict.note.strip():
        table.add_row("note", verdict.note)
    table.add_row("why", verdict.reason)
    return Panel(table, title="Blocked by jury", border_style="yellow")


def _table() -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("field", style="bold")
    table.add_column("value")
    return table
