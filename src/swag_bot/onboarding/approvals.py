"""MCP approval prompter.

``swag serve-mcp`` must not use the terminal prompter. Stdout and stdin are
the stdio protocol channel. This prompter never prints and never reads stdin.

A task-level elicitation can set ``allow_risky``. Otherwise an action is
allowed only when ``$SWAG_HOME/mcp-approvals.json`` preapproves its risk or
kind. Anything else is denied, and the explanation is returned on the MCP
tool result.
"""

from __future__ import annotations

import json
import threading
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from swag_bot.config import swag_home
from swag_bot.interfaces import ActionRequest, RiskLevel

ApprovalReason = Literal[
    "auto",
    "preapproved",
    "elicited",
    "declined",
    "unsupported",
    "empty",
    "unbound",
]

_RISKS = {item.value for item in RiskLevel}
_CURRENT: ContextVar[MCPApprovalPrompter | None] = ContextVar("swag_mcp_prompter", default=None)


class AllowRisky(BaseModel):
    """Form the MCP client shows when it supports elicitation."""

    allow: bool = Field(
        description=(
            "Allow this task to write files and run shell commands. "
            "Destructive actions stay denied unless separately preapproved."
        )
    )


class TaskDecision(BaseModel):
    """Resolver outcome when no elicitation form is sent."""

    allow_risky: bool
    reason: ApprovalReason


class McpApprovals(BaseModel):
    """Preapproved risks and action kinds for MCP sessions."""

    model_config = ConfigDict(extra="ignore")

    risks: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)


class MCPApprovalPrompter:
    """Allow, or deny with an explanation. Never touches stdin or stdout."""

    def __init__(
        self,
        *,
        allow_risky: bool = False,
        reason: ApprovalReason = "unsupported",
        grants: McpApprovals | None = None,
    ) -> None:
        self.allow_risky = allow_risky
        self.reason = reason
        self.grants = grants if grants is not None else McpApprovals()
        self._denials: list[str] = []
        self._lock = threading.Lock()

    def prompt(self, action: ActionRequest) -> bool:
        """Return True to allow ``action``. False denies it and records why."""
        if _granted(action, allow_risky=self.allow_risky, grants=self.grants):
            return True
        text = denial_text(action, reason=self.reason)
        with self._lock:
            self._denials.append(text)
        return False

    def explain(self) -> str:
        """Denial lines recorded by ``prompt``, in order."""
        with self._lock:
            return "\n".join(self._denials)


def current_mcp_prompter() -> MCPApprovalPrompter:
    """Prompter bound for this MCP request, or a deny-by-default prompter."""
    bound = _CURRENT.get()
    if bound is None:
        return MCPApprovalPrompter(reason="unbound")
    return bound


def bind_prompter(prompter: MCPApprovalPrompter) -> Token[MCPApprovalPrompter | None]:
    """Install ``prompter`` for the current context. Pair with ``reset_prompter``."""
    return _CURRENT.set(prompter)


def reset_prompter(token: Token[MCPApprovalPrompter | None]) -> None:
    """Restore the prompter that was current before ``bind_prompter``."""
    _CURRENT.reset(token)


def mcp_approvals_path() -> Path:
    """Path of the MCP preapproval file for this ``SWAG_HOME``."""
    return swag_home() / "mcp-approvals.json"


def load_mcp_approvals() -> McpApprovals:
    """Read preapprovals. A missing or unreadable file grants nothing."""
    path = mcp_approvals_path()
    if not path.is_file():
        return McpApprovals()
    try:
        return McpApprovals.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError, ValueError):
        return McpApprovals()


def save_mcp_approvals(grants: McpApprovals) -> None:
    """Write preapprovals. Creates ``SWAG_HOME`` when needed."""
    path = mcp_approvals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = grants.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def add_grant(token: str) -> McpApprovals:
    """Add a risk or an action kind. Raises ``ValueError`` when it is unknown."""
    name = token.strip()
    grants = load_mcp_approvals()
    if name in _RISKS:
        if name not in grants.risks:
            grants.risks.append(name)
    elif name:
        if name not in grants.kinds:
            grants.kinds.append(name)
    else:
        raise ValueError("grant must not be empty")
    save_mcp_approvals(grants)
    return grants


def denial_text(action: ActionRequest, *, reason: ApprovalReason) -> str:
    """One line the MCP client can show. It does not include secrets."""
    if action.risk is RiskLevel.DESTRUCTIVE:
        why = (
            "Destructive actions are denied over MCP until you preapprove that "
            "risk with `swag setup --grant destructive`."
        )
    elif reason == "declined":
        why = "The MCP client declined the approval, or the form was cancelled."
    elif reason in {"unsupported", "unbound"}:
        why = (
            "This MCP client did not offer form elicitation, and no preapproved "
            "grant covers the action. Approvals are not read from stdin, because "
            "stdin and stdout are the MCP channel."
        )
    elif reason == "empty":
        why = "The task goal was empty."
    else:
        why = "No MCP approval covers this action."
    target = f" {action.target}" if action.target else ""
    return (
        f"Denied {action.kind}{target} (risk {action.risk.value}): {action.summary}. {why} "
        "Preapprove a risk with `swag setup --grant <read|write|execute|network|destructive>` "
        "or run the task in a terminal with `swag run`."
    )


def _granted(action: ActionRequest, *, allow_risky: bool, grants: McpApprovals) -> bool:
    if action.risk.value in set(grants.risks) or action.kind in set(grants.kinds):
        return True
    if allow_risky and action.risk is not RiskLevel.DESTRUCTIVE:
        return True
    return False
