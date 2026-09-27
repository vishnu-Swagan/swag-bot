"""Browser actions over a page port.

The Playwright adapter implements :class:`PagePort`. Unit tests pass a fake.
This module does not import Playwright or the MCP SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from swag_bot.browser.catalog import DOWNLOAD_LIMIT, TEXT_LIMIT, TOOLS
from swag_bot.errors import SandboxError
from swag_bot.interfaces import resolve_sandbox_path

_HTTP = {"http", "https"}
_BLOCKED_SCHEMES = {"javascript", "data", "file", "about", "blob", "chrome"}


@dataclass
class ElementInfo:
    """What the page knows about one element, without returning the whole DOM."""

    found: bool
    tag: str = ""
    input_type: str = ""
    href: str = ""
    text: str = ""


class PagePort(Protocol):
    """The slice of a browser page the session needs."""

    def goto(self, url: str) -> None:
        """Open ``url``."""
        ...

    def url(self) -> str:
        """The current page URL. Empty when nothing is open."""
        ...

    def title(self) -> str:
        """The current document title."""
        ...

    def body_text(self, limit: int) -> str:
        """Visible text, truncated to ``limit`` characters."""
        ...

    def describe(self, selector: str) -> ElementInfo:
        """Describe the first match. ``found`` is false when nothing matches."""
        ...

    def click(self, selector: str) -> None:
        """Click the first match."""
        ...

    def fill(self, selector: str, value: str) -> None:
        """Replace the value of an input."""
        ...

    def type_text(self, selector: str, text: str) -> None:
        """Type ``text`` into the element."""
        ...

    def text_content(self, selector: str) -> str:
        """Text of every match, joined. Empty when nothing matches."""
        ...

    def attribute(self, selector: str, name: str) -> str | None:
        """One attribute of the first match. ``None`` when the element is missing."""
        ...

    def submit(self, selector: str) -> None:
        """Submit the form that owns the element."""
        ...

    def screenshot(self, path: Path) -> None:
        """Write a PNG to ``path``."""
        ...

    def download(self, url: str, path: Path) -> int:
        """Save ``url`` to ``path`` and return the number of bytes written."""
        ...

    def go_back(self) -> None:
        """Return to the previous page in this session."""
        ...


class BrowserSession:
    """Stateful browser actions for one task.

    Hosts opened with :meth:`navigate` are remembered. A click that would
    leave for a new host, or submit a form, is refused so the agent has to
    call the network tool that the permission policy can approve.
    """

    def __init__(self, page: PagePort, output_dir: Path) -> None:
        self._page = page
        self._output = output_dir
        self._hosts: set[str] = set()

    @property
    def hosts(self) -> set[str]:
        """Hosts successfully opened in this session, without a leading ``www.``."""
        return set(self._hosts)

    def run(self, name: str, arguments: Mapping[str, object]) -> str:
        """Run one catalog tool. Unknown names return an error string."""
        short = name.split("__")[-1]
        if short not in TOOLS:
            return f"error: unknown browser tool {name}"
        try:
            if short == "navigate":
                return self.navigate(_text(arguments.get("url")))
            if short == "snapshot":
                return self.snapshot()
            if short == "click":
                return self.click(_text(arguments.get("selector")))
            if short == "type_text":
                return self.type_text(
                    _text(arguments.get("selector")),
                    _text(arguments.get("text"), allow_empty=True),
                )
            if short == "fill":
                return self.fill(
                    _text(arguments.get("selector")),
                    _text(arguments.get("value"), allow_empty=True),
                )
            if short == "submit":
                return self.submit(_text(arguments.get("selector")), _text(arguments.get("url")))
            if short == "screenshot":
                return self.screenshot(_text(arguments.get("path")))
            if short == "extract":
                return self.extract(
                    _text(arguments.get("selector")),
                    _optional(arguments.get("attribute")),
                )
            if short == "download":
                return self.download(_text(arguments.get("url")), _text(arguments.get("path")))
        except Exception as exc:
            return _fail(exc)
        return f"error: unknown browser tool {name}"

    def navigate(self, url: str) -> str:
        """Open ``url``. The result says whether the host is new to this session."""
        if not url:
            return "error: url is required"
        host = host_key(url)
        if host is None:
            return "error: url must be an http or https URL"
        new = host not in self._hosts
        try:
            self._page.goto(url)
        except Exception as exc:
            return _fail(exc)
        opened = self._page.url() or url
        opened_host = host_key(opened) or host
        if opened_host not in self._hosts:
            new = True
        self._hosts.add(host)
        self._hosts.add(opened_host)
        label = "new domain" if new else "known domain"
        title = self._page.title().strip()
        return f"opened {opened} ({label})\ntitle: {title}"

    def snapshot(self) -> str:
        """Title, URL, and visible text of the open page."""
        try:
            url = self._page.url()
            title = self._page.title().strip()
            body = self._page.body_text(TEXT_LIMIT)
        except Exception as exc:
            return _fail(exc)
        if not url or url == "about:blank":
            return "no page is open"
        return f"title: {title}\nurl: {url}\n\n{_clip(body, TEXT_LIMIT)}"

    def click(self, selector: str) -> str:
        """Click ``selector`` unless it would submit a form or open a new domain."""
        if not selector:
            return "error: selector is required"
        try:
            info = self._page.describe(selector)
        except Exception as exc:
            return _fail(exc)
        if not info.found:
            return f"error: no element matches {selector}"
        if is_submit(info):
            return (
                "error: this control submits a form. "
                "Call submit with the page or form-action URL so it can be approved."
            )
        if info.href:
            blocked, host = resolve_link(info.href, self._page.url())
            if blocked:
                return "error: that link is not an http or https URL"
            if host and host not in self._hosts:
                return (
                    f"error: this link opens {host}, a new domain. "
                    "Call navigate with that URL so it can be approved."
                )
        before = self._page.url()
        try:
            self._page.click(selector)
        except Exception as exc:
            return _fail(exc)
        after = self._page.url()
        after_host = host_key(after)
        if after_host and after_host not in self._hosts:
            self._restore(before)
            return (
                f"error: that click opened {after_host}, a new domain. "
                "Call navigate with that URL so it can be approved."
            )
        if after_host:
            self._hosts.add(after_host)
        return f"clicked {selector}\nurl: {self._page.url() or before}"

    def type_text(self, selector: str, text: str) -> str:
        """Type into an element. A newline is treated as an attempt to submit."""
        if not selector:
            return "error: selector is required"
        if "\n" in text or "\r" in text:
            return "error: type_text cannot submit a form. Call submit so it can be approved."
        try:
            info = self._page.describe(selector)
            if not info.found:
                return f"error: no element matches {selector}"
            self._page.type_text(selector, text)
        except Exception as exc:
            return _fail(exc)
        return f"typed into {selector}"

    def fill(self, selector: str, value: str) -> str:
        """Replace an input value. Does not submit."""
        if not selector:
            return "error: selector is required"
        try:
            info = self._page.describe(selector)
            if not info.found:
                return f"error: no element matches {selector}"
            self._page.fill(selector, value)
        except Exception as exc:
            return _fail(exc)
        return f"filled {selector}"

    def submit(self, selector: str, url: str) -> str:
        """Submit a form whose destination host is the host of ``url``."""
        if not selector:
            return "error: selector is required"
        if not url:
            return "error: url is required"
        approved = host_key(url)
        if approved is None:
            return "error: url must be the http or https page or form action being approved"
        try:
            info = self._page.describe(selector)
        except Exception as exc:
            return _fail(exc)
        if not info.found:
            return f"error: no element matches {selector}"
        destination = host_key(self._page.url())
        if info.href:
            blocked, host = resolve_link(info.href, self._page.url())
            if blocked:
                return "error: the form action is not an http or https URL"
            if host:
                destination = host
        if destination is None:
            return "error: no http page is open"
        if destination != approved:
            return (
                f"error: this form sends data to {destination}, "
                f"but the approved url is {url}. "
                "Call submit again with the destination URL."
            )
        try:
            self._page.submit(selector)
        except Exception as exc:
            return _fail(exc)
        if destination:
            self._hosts.add(destination)
        return f"submitted {selector}\nurl: {self._page.url() or url}"

    def screenshot(self, path: str) -> str:
        """Write a PNG under the output directory."""
        located = self._output_file(path)
        if isinstance(located, str):
            return located
        target, relative = located
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._page.screenshot(target)
        except Exception as exc:
            return _fail(exc)
        return f"saved {relative}"

    def extract(self, selector: str, attribute: str | None = None) -> str:
        """Text or one attribute of the elements matching ``selector``."""
        if not selector:
            return "error: selector is required"
        try:
            if attribute:
                value = self._page.attribute(selector, attribute)
                if value is None:
                    return f"error: no element matches {selector}"
                return _clip(value, TEXT_LIMIT)
            info = self._page.describe(selector)
            if not info.found:
                return f"error: no element matches {selector}"
            return _clip(self._page.text_content(selector), TEXT_LIMIT)
        except Exception as exc:
            return _fail(exc)

    def download(self, url: str, path: str) -> str:
        """Save ``url`` under the output directory."""
        if not url:
            return "error: url is required"
        if host_key(url) is None:
            return "error: url must be an http or https URL"
        located = self._output_file(path)
        if isinstance(located, str):
            return located
        target, relative = located
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            size = self._page.download(url, target)
        except Exception as exc:
            return _fail(exc)
        if size > DOWNLOAD_LIMIT:
            target.unlink(missing_ok=True)
            return "error: download is larger than 20 MB"
        return f"downloaded {size} bytes to {relative}"

    def _output_file(self, path: str) -> tuple[Path, str] | str:
        if not path:
            return "error: path is required"
        try:
            target = resolve_sandbox_path(self._output, path)
        except SandboxError as exc:
            return f"error: {exc}"
        relative = target.relative_to(self._output.resolve()).as_posix()
        return target, relative

    def _restore(self, url: str) -> None:
        try:
            self._page.go_back()
        except Exception:
            pass
        if url and self._page.url() != url:
            try:
                self._page.goto(url)
            except Exception:
                pass


def host_key(url: str) -> str | None:
    """Hostname of an http(s) URL, lowercased, without a leading ``www.``."""
    parsed = urlsplit(url.strip())
    if parsed.scheme not in _HTTP or not parsed.hostname:
        return None
    host = parsed.hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def resolve_link(href: str, current_url: str) -> tuple[bool, str | None]:
    """Return ``(blocked, host)`` for a link or form action.

    Relative links stay on the current host. ``javascript:``, ``data:``, and
    ``file:`` URLs are blocked.
    """
    text = href.strip()
    if not text or text.startswith("#"):
        return False, host_key(current_url)
    parsed = urlsplit(text)
    if parsed.scheme in _BLOCKED_SCHEMES:
        return True, None
    if parsed.scheme and parsed.scheme not in _HTTP:
        return True, None
    if text.startswith("//"):
        return False, host_key(f"https:{text}")
    if not parsed.netloc:
        return False, host_key(current_url)
    return False, host_key(text if parsed.scheme in _HTTP else f"https://{text}")


def is_submit(info: ElementInfo) -> bool:
    """True for controls that send a form."""
    if not info.found:
        return False
    tag = info.tag.lower()
    kind = info.input_type.lower()
    if tag == "input" and kind in {"submit", "image"}:
        return True
    if tag == "button" and kind in {"", "submit"}:
        return True
    if tag == "form":
        return True
    return False


def _text(value: object, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    if allow_empty:
        return value
    return value.strip()


def _optional(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _fail(exc: BaseException) -> str:
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    if len(message) > 300:
        message = message[:297] + "..."
    return f"error: {message}"
