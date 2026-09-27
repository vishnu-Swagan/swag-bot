"""The browser thread runs actions without launching Chromium."""

from __future__ import annotations

from pathlib import Path

from swag_bot.browser.service import BrowserService
from tests.browser.fake_page import FakePage


def test_service_reuses_one_page(tmp_path: Path) -> None:
    page = FakePage()
    service = BrowserService(opener=lambda: page, output_dir=tmp_path, timeout=5)
    try:
        first = service.call("navigate", url="https://example.com")
        second = service.call("navigate", url="https://example.com/docs")
    finally:
        service.close()
    assert "new domain" in first
    assert "known domain" in second
    assert page.location == "https://example.com/docs"


def test_service_reports_an_opener_failure(tmp_path: Path) -> None:
    def explode() -> FakePage:
        raise RuntimeError("chromium missing")

    service = BrowserService(opener=explode, output_dir=tmp_path, timeout=5)
    try:
        result = service.call("snapshot")
    finally:
        service.close()
    assert result.startswith("error:")
    assert "chromium missing" in result
