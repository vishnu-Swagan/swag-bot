"""In-memory page for browser session tests."""

from __future__ import annotations

from pathlib import Path

from swag_bot.browser.session import ElementInfo


class FakePage:
    """Records browser calls and serves scripted elements."""

    def __init__(self) -> None:
        self.location = "about:blank"
        self.page_title = ""
        self.body = ""
        self.elements: dict[str, ElementInfo] = {}
        self.values: dict[str, str] = {}
        self.clicks: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.fills: list[tuple[str, str]] = []
        self.submits: list[str] = []
        self.shots: list[Path] = []
        self.downloads: list[tuple[str, Path]] = []
        self.history: list[str] = []
        self.click_goes_to: dict[str, str] = {}
        self.download_size: int | None = None
        self.fail_back = False

    def goto(self, url: str) -> None:
        self.history.append(self.location)
        self.location = url
        self.page_title = "Example"
        self.body = f"Hello from {url}"

    def url(self) -> str:
        return self.location

    def title(self) -> str:
        return self.page_title

    def body_text(self, limit: int) -> str:
        return self.body[:limit]

    def describe(self, selector: str) -> ElementInfo:
        info = self.elements.get(selector)
        if info is None:
            return ElementInfo(found=False)
        return info

    def click(self, selector: str) -> None:
        self.clicks.append(selector)
        if selector in self.click_goes_to:
            self.history.append(self.location)
            self.location = self.click_goes_to[selector]

    def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))
        self.values[selector] = value

    def type_text(self, selector: str, text: str) -> None:
        self.typed.append((selector, text))
        self.values[selector] = self.values.get(selector, "") + text

    def text_content(self, selector: str) -> str:
        info = self.elements.get(selector)
        return info.text if info is not None else ""

    def attribute(self, selector: str, name: str) -> str | None:
        info = self.elements.get(selector)
        if info is None:
            return None
        if name == "href":
            return info.href
        if name == "value":
            return self.values.get(selector, "")
        return None

    def submit(self, selector: str) -> None:
        self.submits.append(selector)

    def screenshot(self, path: Path) -> None:
        path.write_bytes(b"png")
        self.shots.append(path)

    def download(self, url: str, path: Path) -> int:
        payload = b"file-bytes"
        path.write_bytes(payload)
        self.downloads.append((url, path))
        if self.download_size is not None:
            return self.download_size
        return len(payload)

    def go_back(self) -> None:
        if self.fail_back:
            raise RuntimeError("no history")
        if self.history:
            self.location = self.history.pop()
