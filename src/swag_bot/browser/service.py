"""One Chromium instance on a dedicated thread.

Playwright's sync API has to stay on the thread that started it. MCP tool
calls arrive on worker threads, so they hand the work to this one.
"""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from swag_bot.browser.session import BrowserSession, PagePort


def default_output_dir() -> Path:
    """Where screenshots and downloads are written.

    ``SWAG_BROWSER_OUTPUT`` wins. Otherwise the current directory is used.
    The directory is created if it is missing.
    """
    raw = os.environ.get("SWAG_BROWSER_OUTPUT", "").strip()
    path = Path(raw).expanduser() if raw else Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def open_playwright_page() -> PagePort:
    """Launch headless Chromium. Raises ``SwagError`` when it cannot."""
    from swag_bot.browser.playwright_page import PlaywrightPage

    return PlaywrightPage()


class BrowserService:
    """Serializes browser calls onto one thread and one page."""

    def __init__(
        self,
        *,
        opener: Callable[[], PagePort] | None = None,
        output_dir: Path | None = None,
        timeout: float = 60,
    ) -> None:
        self._opener = opener or open_playwright_page
        self._output = output_dir
        self._timeout = timeout
        self._jobs: queue.Queue[tuple[str, Mapping[str, object], queue.Queue[str]] | None] = (
            queue.Queue()
        )
        self._thread = threading.Thread(target=self._loop, name="swag-browser", daemon=True)
        self._thread.start()

    def call(self, name: str, **arguments: object) -> str:
        """Run one browser tool and return its text result."""
        box: queue.Queue[str] = queue.Queue(maxsize=1)
        self._jobs.put((name, arguments, box))
        try:
            return box.get(timeout=self._timeout)
        except queue.Empty:
            return "error: the browser did not respond in time"

    def close(self) -> None:
        """Stop the browser thread. Safe to call more than once."""
        if not self._thread.is_alive():
            return
        self._jobs.put(None)
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        session: BrowserSession | None = None
        page: PagePort | None = None
        while True:
            job = self._jobs.get()
            if job is None:
                break
            name, arguments, box = job
            try:
                if session is None:
                    page = self._opener()
                    session = BrowserSession(page, _directory(self._output))
                box.put(session.run(name, arguments))
            except Exception as exc:
                text = str(exc).strip()
                message = text.splitlines()[0] if text else exc.__class__.__name__
                box.put(f"error: {message}")
        if page is not None:
            closer = getattr(page, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass


def _directory(path: Path | None) -> Path:
    if path is None:
        return default_output_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
