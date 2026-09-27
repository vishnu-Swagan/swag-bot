"""Playwright page adapter. Imported only when a browser is actually launched."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from swag_bot.browser.catalog import DOWNLOAD_LIMIT
from swag_bot.browser.session import ElementInfo
from swag_bot.errors import SwagError

_INSTALL = (
    "Playwright is not installed. Install the browser extra with "
    "pip install 'swag-bot[browser]', then download Chromium with "
    "python -m playwright install chromium"
)

_SUBMIT = """el => {
  const tag = (el.tagName || "").toLowerCase();
  const form = tag === "form" ? el : el.form;
  if (form) form.requestSubmit(tag === "form" ? undefined : el);
  else el.click();
}"""

_DESCRIBE = """el => {
  const tag = (el.tagName || "").toLowerCase();
  const type = (el.getAttribute("type") || "").toLowerCase();
  let href = "";
  if (tag === "a" || tag === "area") {
    href = typeof el.href === "string" ? el.href : "";
  } else if (tag === "form") {
    href = typeof el.action === "string" ? el.action : "";
  } else if (tag === "button" || tag === "input") {
    const formaction = el.getAttribute("formaction");
    const submits = type === "submit" || type === "image" || (tag === "button" && !type);
    if (formaction) href = formaction;
    else if (submits && el.form && typeof el.form.action === "string") href = el.form.action;
  }
  const text = ((el.innerText || el.textContent || "") + "").slice(0, 200);
  return {tag, type, href, text};
}"""


def _headed() -> bool:
    return os.environ.get("SWAG_BROWSER_HEADED", "").strip().lower() in {"1", "true", "yes"}


def _timeout_ms() -> int:
    raw = os.environ.get("SWAG_BROWSER_TIMEOUT", "").strip()
    if not raw:
        return 20_000
    try:
        seconds = float(raw)
    except ValueError:
        return 20_000
    if seconds <= 0:
        return 20_000
    return int(seconds * 1000)


class PlaywrightPage:
    """One headless Chromium page. ``close`` is safe to call more than once."""

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SwagError(_INSTALL) from exc
        self._timeout_ms = _timeout_ms()
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        try:
            manager = sync_playwright().start()
            self._playwright = manager
            browser = manager.chromium.launch(headless=not _headed())
            self._browser = browser
            context = browser.new_context(
                accept_downloads=False,
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()
            page.set_default_timeout(self._timeout_ms)
            self._page = page
        except SwagError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise SwagError(
                "Could not launch headless Chromium. "
                "Install it with: python -m playwright install chromium. "
                f"({exc})"
            ) from exc

    def close(self) -> None:
        """Stop Chromium. Safe to call more than once."""
        browser = self._browser
        manager = self._playwright
        self._browser = None
        self._page = None
        self._playwright = None
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if manager is not None:
            try:
                manager.stop()
            except Exception:
                pass

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")

    def url(self) -> str:
        value = self._page.url
        return value if isinstance(value, str) else ""

    def title(self) -> str:
        value = self._page.title()
        return value if isinstance(value, str) else ""

    def body_text(self, limit: int) -> str:
        text = self._page.inner_text("body")
        if not isinstance(text, str):
            return ""
        return text[:limit]

    def describe(self, selector: str) -> ElementInfo:
        locator = self._page.locator(selector)
        if locator.count() == 0:
            return ElementInfo(found=False)
        raw = locator.first.evaluate(_DESCRIBE)
        if not isinstance(raw, dict):
            return ElementInfo(found=True)
        return ElementInfo(
            found=True,
            tag=_str(raw.get("tag")),
            input_type=_str(raw.get("type")),
            href=_str(raw.get("href")),
            text=_str(raw.get("text")),
        )

    def click(self, selector: str) -> None:
        self._page.locator(selector).first.click()

    def fill(self, selector: str, value: str) -> None:
        self._page.locator(selector).first.fill(value)

    def type_text(self, selector: str, text: str) -> None:
        self._page.locator(selector).first.type(text)

    def text_content(self, selector: str) -> str:
        locator = self._page.locator(selector)
        count = locator.count()
        parts: list[str] = []
        for index in range(count):
            value = locator.nth(index).inner_text()
            if isinstance(value, str) and value:
                parts.append(value)
        return "\n".join(parts)

    def attribute(self, selector: str, name: str) -> str | None:
        locator = self._page.locator(selector)
        if locator.count() == 0:
            return None
        value = locator.first.get_attribute(name)
        return value if isinstance(value, str) else None

    def submit(self, selector: str) -> None:
        locator = self._page.locator(selector).first
        try:
            with self._page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            ):
                locator.evaluate(_SUBMIT)
        except Exception as exc:
            # A form that stays on the page does not navigate. Other failures
            # (a missing control, a browser crash) still surface to the caller.
            if "Timeout" in exc.__class__.__name__:
                return
            raise

    def screenshot(self, path: Path) -> None:
        self._page.screenshot(path=str(path), full_page=False)

    def download(self, url: str, path: Path) -> int:
        response = self._page.request.get(url, timeout=self._timeout_ms)
        status = int(response.status)
        if status >= 400:
            raise RuntimeError(f"download failed: HTTP {status}")
        header = response.headers.get("content-length")
        if isinstance(header, str) and header.isdigit() and int(header) > DOWNLOAD_LIMIT:
            raise RuntimeError("download is larger than 20 MB")
        body = response.body()
        if not isinstance(body, bytes):
            body = bytes(body)
        if len(body) > DOWNLOAD_LIMIT:
            raise RuntimeError("download is larger than 20 MB")
        path.write_bytes(body)
        return len(body)

    def go_back(self) -> None:
        self._page.go_back(wait_until="domcontentloaded")


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""
