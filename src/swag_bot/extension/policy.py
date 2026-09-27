"""Risk labels for Chrome-tab tools.

The plan-do-verify executor classifies an unknown tool name as ``execute``
because its kind is ``tool``. The headless browser plugin (tool names
``browser__navigate``, ``browser__snapshot``, and the rest) uses finer risks:
reads stay reads, typing is a write, and opening a URL or submitting a form
is network. This wrapper applies that table so the side panel asks at the
same times the headless plugin would.

It does not lower a destructive classification. A hard deny from the inner
policy, including a missing plugin grant, is kept.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from swag_bot.interfaces import (
    ActionRequest,
    AutonomyLevel,
    PermissionPolicy,
    RiskLevel,
    default_requires_approval,
)
from swag_bot.safety.policy import PolicyDecision
from swag_bot.safety.redact import redact_text

# Public tool name -> risk. Keep this aligned with plugins/browser on the
# browser-plugin branch: snapshot and extract are reads, typing and fill are
# writes, click is execute, navigate and submit are network.
TAB_RISK: dict[str, RiskLevel] = {
    "browser__snapshot": RiskLevel.READ,
    "browser__extract": RiskLevel.READ,
    "browser__type_text": RiskLevel.WRITE,
    "browser__fill": RiskLevel.WRITE,
    "browser__click": RiskLevel.EXECUTE,
    "browser__navigate": RiskLevel.NETWORK,
    "browser__submit": RiskLevel.NETWORK,
}

_SHORT_NAMES = {name.removeprefix("browser__") for name in TAB_RISK}


def tab_tool_name(action: ActionRequest) -> str | None:
    """Return the ``browser__*`` name this action refers to, if it is one."""
    summary = action.summary.strip()
    for name in TAB_RISK:
        if summary == name or summary.startswith(name + " "):
            return name
    server = action.arguments.get("server")
    tool = action.arguments.get("tool")
    if server == "browser" and isinstance(tool, str) and tool in _SHORT_NAMES:
        return f"browser__{tool}"
    target = action.target or ""
    if target in TAB_RISK:
        return target
    return None


class CatalogRiskPolicy:
    """Inner permission policy with the browser-tool risk table applied."""

    def __init__(self, inner: PermissionPolicy) -> None:
        self._inner = inner

    @property
    def autonomy(self) -> AutonomyLevel:
        return self._inner.autonomy

    def classify(self, action: ActionRequest) -> RiskLevel:
        """Catalog risk for a tab tool. Anything else is the inner policy's call.

        A destructive classification from the action or the inner policy is
        kept. The catalog may label a snapshot as ``read`` even when the
        executor's generic tool kind would have said ``execute``.
        """
        inner_risk = self._inner.classify(action)
        if action.risk is RiskLevel.DESTRUCTIVE or inner_risk is RiskLevel.DESTRUCTIVE:
            return RiskLevel.DESTRUCTIVE
        catalog = TAB_RISK.get(tab_tool_name(action) or "")
        if catalog is None:
            return inner_risk
        return catalog

    def requires_approval(self, action: ActionRequest) -> bool:
        """Ask as often as ``default_requires_approval`` for the catalog risk."""
        return default_requires_approval(self.autonomy, self.classify(action))

    def decide(self, action: ActionRequest) -> PolicyDecision:
        """Keep a hard deny. Tab tools then follow the catalog risk."""
        if _inner_denied(self._inner, action):
            return PolicyDecision.DENY
        if tab_tool_name(action) is None:
            delegated = _delegate_decision(self._inner, action)
            if delegated is not None:
                return delegated
        if self.requires_approval(action):
            return PolicyDecision.PROMPT
        return PolicyDecision.ALLOW


def _inner_denied(policy: PermissionPolicy, action: ActionRequest) -> bool:
    denied = getattr(policy, "is_denied", None)
    if not callable(denied):
        return False
    return bool(denied(action))


def _delegate_decision(policy: PermissionPolicy, action: ActionRequest) -> PolicyDecision | None:
    decide = getattr(policy, "decide", None)
    if not callable(decide):
        return None
    raw: Any = decide(action)
    if isinstance(raw, PolicyDecision):
        return raw
    value = getattr(raw, "value", raw)
    text = str(value)
    if text in {"allow", "prompt", "deny"}:
        return PolicyDecision(text)
    return None


def approval_view(action: ActionRequest) -> dict[str, Any]:
    """Fields the side panel shows. Secrets in the preview are redacted."""
    arguments: Mapping[str, Any] = action.arguments
    url = _str_arg(arguments, "url")
    selector = _str_arg(arguments, "selector")
    preview = _str_arg(arguments, "text") or _str_arg(arguments, "value")
    name = tab_tool_name(action) or action.summary
    summary = name
    if url and url not in summary:
        summary = f"{summary} {url}"
    elif action.target and action.target not in summary:
        summary = f"{summary} {action.target}"
    view: dict[str, Any] = {
        "kind": action.kind,
        "risk": action.risk.value,
        "tool": name,
        "summary": redact_text(summary),
    }
    if action.target:
        view["target"] = redact_text(action.target)
    if url:
        view["url"] = redact_text(url)
    if selector:
        view["selector"] = selector
    if preview:
        view["text"] = redact_text(_clip_preview(preview))
    return view


def _str_arg(arguments: Mapping[str, Any], key: str) -> str:
    value = arguments.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def _clip_preview(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
