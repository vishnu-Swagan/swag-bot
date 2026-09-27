"""Chrome-tab tools with the same names as the headless browser plugin.

Screenshot and download stay with that plugin. A screenshot of the real tab
does not fit in a native-messaging message, and a download writes a file
outside the tab. The tools that are here act on the user's open tab, and
only after the permission policy has allowed the call.

Click refuses a submit control or a link to another site. The model has to
call ``browser__submit`` or ``browser__navigate``, which are network actions
and get their own approval.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from typing import Any, Protocol

from swag_bot.extension.bridge import BridgeClosed, BridgeTimeout
from swag_bot.extension.policy import TAB_RISK
from swag_bot.extension.protocol import clip_text
from swag_bot.interfaces import Tool, ToolRegistry

TEXT_LIMIT = 8000
_URL_LIMIT = 2000
_SELECTOR_LIMIT = 500
_TEXT_LIMIT = 20_000
_TAB_TIMEOUT = 20.0

_DESCRIPTIONS: dict[str, str] = {
    "browser__navigate": (
        "Open an http or https URL in the user's current Chrome tab. "
        "This is a network action. A host this tab has not opened is a new site: "
        "pass that URL here instead of clicking the link."
    ),
    "browser__snapshot": (
        "Read the user's current Chrome tab: its title, URL, and visible text. "
        "Does not navigate or change the page."
    ),
    "browser__click": (
        "Click an element in the user's current Chrome tab by CSS selector. "
        "Refuses submit buttons and links that leave for a new site. "
        "Use browser__submit or browser__navigate for those, so they can be approved."
    ),
    "browser__type_text": (
        "Type text into an element in the user's current Chrome tab by CSS selector. "
        "Does not submit the form."
    ),
    "browser__fill": (
        "Replace the value of an input or textarea in the user's current Chrome tab "
        "by CSS selector. Does not submit the form."
    ),
    "browser__submit": (
        "Submit a form in the user's current Chrome tab. "
        "Pass url as the page URL or the form action the user is approving. "
        "This sends data off the page and is a network action."
    ),
    "browser__extract": (
        "Read the text, or one attribute, of the elements matching a CSS selector "
        "in the user's current Chrome tab. Does not change the page."
    ),
}


class TabResponder(Protocol):
    """The slice of ``PortBridge`` the tab tools need."""

    def request(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float | None,
    ) -> Mapping[str, Any]:
        """Send one request and return the extension's reply."""
        ...


class RunCancelled(Exception):
    """The person cancelled the task from the side panel."""


class TabDispatcher:
    """Ask the extension to perform one already-approved tab action."""

    def __init__(
        self,
        bridge: TabResponder,
        *,
        run_id: str,
        cancel: Any = None,
    ) -> None:
        self._bridge = bridge
        self._run_id = run_id
        self._cancel = cancel

    def call(self, name: str, arguments: Mapping[str, Any]) -> str:
        """Validate ``arguments``, perform the action, and return text."""
        if self._cancelled():
            raise RunCancelled("cancelled")
        try:
            cleaned = validate_tab_arguments(name, arguments)
        except ValueError as exc:
            return f"error: {exc}"
        payload: dict[str, Any] = {
            "type": "tab_action",
            "id": self._run_id,
            "tool": name,
            "arguments": cleaned,
        }
        try:
            result = self._bridge.request(payload, timeout=_TAB_TIMEOUT)
        except BridgeTimeout:
            return "error: the Chrome tab did not respond"
        except BridgeClosed:
            return "error: the Chrome extension disconnected"
        if self._cancelled():
            raise RunCancelled("cancelled")
        return format_tab_result(name, result)

    def _cancelled(self) -> bool:
        cancel = self._cancel
        if cancel is None:
            return False
        is_set = getattr(cancel, "is_set", None)
        return bool(callable(is_set) and is_set())


def register_chrome_tab_tools(registry: ToolRegistry, dispatcher: TabDispatcher) -> None:
    """Register the tab tools. An existing name is replaced for this run."""
    for name in TAB_RISK:
        registry.register(_tool(name), _handler(dispatcher, name))


def validate_tab_arguments(name: str, arguments: Mapping[str, Any]) -> dict[str, str]:
    """Return the arguments the extension may receive. Raise ``ValueError`` if not."""
    if name not in TAB_RISK:
        raise ValueError(f"unknown tab tool: {name}")
    if name == "browser__snapshot":
        return {}
    if name == "browser__navigate":
        return {"url": check_http_url(arguments.get("url"))}
    if name == "browser__click":
        return {"selector": check_selector(arguments.get("selector"))}
    if name == "browser__type_text":
        return {
            "selector": check_selector(arguments.get("selector")),
            "text": check_text(arguments.get("text"), field="text"),
        }
    if name == "browser__fill":
        return {
            "selector": check_selector(arguments.get("selector")),
            "value": check_text(arguments.get("value"), field="value"),
        }
    if name == "browser__submit":
        return {
            "selector": check_selector(arguments.get("selector")),
            "url": check_http_url(arguments.get("url")),
        }
    if name == "browser__extract":
        cleaned = {"selector": check_selector(arguments.get("selector"))}
        attribute = arguments.get("attribute", "")
        if attribute is None:
            attribute = ""
        cleaned["attribute"] = check_text(attribute, field="attribute", limit=200)
        return cleaned
    raise ValueError(f"unknown tab tool: {name}")


def check_http_url(value: object) -> str:
    """Require an http(s) URL with no embedded username or password."""
    if not isinstance(value, str):
        raise ValueError("url must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _URL_LIMIT:
        raise ValueError("url must be an http or https URL")
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an http or https URL")
    if parsed.username or parsed.password:
        raise ValueError("url must not include a username or password")
    return cleaned


def check_selector(value: object) -> str:
    """Require one non-empty CSS selector line."""
    if not isinstance(value, str):
        raise ValueError("selector must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("selector is required")
    if len(cleaned) > _SELECTOR_LIMIT:
        raise ValueError("selector is too long")
    if "\n" in cleaned or "\r" in cleaned or "\x00" in cleaned:
        raise ValueError("selector must be one line")
    return cleaned


def check_text(value: object, *, field: str, limit: int = _TEXT_LIMIT) -> str:
    """Require a string no longer than ``limit``."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if "\x00" in value:
        raise ValueError(f"{field} must not contain NUL")
    if len(value) > limit:
        raise ValueError(f"{field} is too long")
    return value


def format_tab_result(name: str, payload: Mapping[str, Any]) -> str:
    """Text the model sees after the extension answers."""
    if payload.get("ok") is not True:
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return f"error: {clip_text(error.strip(), 500)}"
        return "error: the tab action failed"
    title = _field(payload, "title")
    url = _field(payload, "url")
    content = _field(payload, "content")
    detail = _field(payload, "detail")
    if name == "browser__snapshot" or name == "browser__extract":
        lines = [
            line
            for line in (f"title: {title}" if title else "", f"url: {url}" if url else "")
            if line
        ]
        body = content or detail
        if body:
            lines.append("")
            lines.append(body)
        text = "\n".join(lines).strip() or "The page had no readable text."
        return clip_text(text, TEXT_LIMIT)
    if name == "browser__navigate":
        landed = url or detail
        text = f"navigated to {landed}" if landed else "navigated"
        if title:
            text = f"{text}\ntitle: {title}"
        return clip_text(text, TEXT_LIMIT)
    if name == "browser__click":
        text = "clicked"
        if detail:
            text = f"clicked {detail}"
        if url:
            text = f"{text}\nurl: {url}"
        return clip_text(text, TEXT_LIMIT)
    if name == "browser__submit":
        text = "submitted"
        if url:
            text = f"{text}\nurl: {url}"
        return text
    if name in {"browser__type_text", "browser__fill"}:
        return detail or ("typed" if name == "browser__type_text" else "filled")
    return clip_text(detail or content or "ok", TEXT_LIMIT)


def _tool(name: str) -> Tool:
    return Tool(name=name, description=_DESCRIPTIONS[name], parameters=_parameters(name))


def _parameters(name: str) -> dict[str, Any]:
    if name == "browser__snapshot":
        return {"type": "object", "properties": {}}
    if name == "browser__navigate":
        return _object({"url": _string("http or https URL to open.")}, ("url",))
    if name == "browser__click":
        return _object(
            {"selector": _string("CSS selector of the element to click.")},
            ("selector",),
        )
    if name == "browser__type_text":
        return _object(
            {
                "selector": _string("CSS selector of the element."),
                "text": _string("Text to type. This does not submit the form."),
            },
            ("selector", "text"),
        )
    if name == "browser__fill":
        return _object(
            {
                "selector": _string("CSS selector of the input or textarea."),
                "value": _string("Replacement value. This does not submit the form."),
            },
            ("selector", "value"),
        )
    if name == "browser__submit":
        return _object(
            {
                "selector": _string("CSS selector of the form or a control inside it."),
                "url": _string("Page URL or form action the user is approving."),
            },
            ("selector", "url"),
        )
    return _object(
        {
            "selector": _string("CSS selector of the elements to read."),
            "attribute": _string("Attribute name. Omit it to read text."),
        },
        ("selector",),
    )


def _object(properties: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _handler(dispatcher: TabDispatcher, name: str) -> Any:
    def handler(**arguments: Any) -> str:
        return dispatcher.call(name, arguments)

    return handler


def _field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""
