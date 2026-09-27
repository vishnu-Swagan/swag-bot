"""Browser actions against a fake page. No Chromium."""

from __future__ import annotations

from pathlib import Path

from swag_bot.browser.catalog import DOWNLOAD_LIMIT
from swag_bot.browser.session import BrowserSession, ElementInfo, host_key
from tests.browser.fake_page import FakePage


def _session(tmp_path: Path) -> tuple[BrowserSession, FakePage]:
    page = FakePage()
    return BrowserSession(page, tmp_path), page


def test_navigate_marks_a_new_domain_then_the_same_host(tmp_path: Path) -> None:
    session, _page = _session(tmp_path)
    first = session.navigate("https://www.example.com/docs")
    assert "new domain" in first
    assert "example.com" in first
    second = session.navigate("https://example.com/other")
    assert "known domain" in second
    assert session.hosts == {"example.com"}


def test_navigate_rejects_non_http_urls(tmp_path: Path) -> None:
    session, page = _session(tmp_path)
    assert session.navigate("file:///etc/passwd").startswith("error:")
    assert session.navigate("javascript:alert(1)").startswith("error:")
    assert session.navigate("").startswith("error:")
    assert page.location == "about:blank"


def test_snapshot_and_extract_read_the_open_page(tmp_path: Path) -> None:
    session, page = _session(tmp_path)
    assert session.snapshot() == "no page is open"
    session.navigate("https://example.com")
    page.elements["#price"] = ElementInfo(found=True, tag="p", text="Price: 42")
    page.elements["#q"] = ElementInfo(found=True, tag="input", input_type="text")
    page.values["#q"] = "widgets"
    assert "Hello from https://example.com" in session.snapshot()
    assert session.extract("#price") == "Price: 42"
    assert session.extract("#q", "value") == "widgets"
    assert session.extract("#missing").startswith("error:")


def test_click_refuses_submit_and_a_new_domain(tmp_path: Path) -> None:
    session, page = _session(tmp_path)
    session.navigate("https://example.com")
    page.elements["#go"] = ElementInfo(found=True, tag="button", input_type="submit")
    page.elements["#away"] = ElementInfo(
        found=True,
        tag="a",
        href="https://other.test/leave",
    )
    page.elements["#same"] = ElementInfo(found=True, tag="a", href="https://example.com/next")
    page.click_goes_to["#same"] = "https://example.com/next"
    assert "submit" in session.click("#go")
    assert page.clicks == []
    refused = session.click("#away")
    assert "new domain" in refused
    assert "other.test" in refused
    assert page.clicks == []
    assert "clicked #same" in session.click("#same")
    assert page.clicks == ["#same"]


def test_click_that_changes_host_goes_back(tmp_path: Path) -> None:
    session, page = _session(tmp_path)
    session.navigate("https://example.com")
    page.elements["#sneaky"] = ElementInfo(found=True, tag="button", input_type="button")
    page.click_goes_to["#sneaky"] = "https://evil.test/"
    result = session.click("#sneaky")
    assert "evil.test" in result
    assert host_key(page.url()) == "example.com"
    assert "evil.test" not in session.hosts


def test_type_and_fill_do_not_submit(tmp_path: Path) -> None:
    session, page = _session(tmp_path)
    session.navigate("https://example.com")
    page.elements["#q"] = ElementInfo(found=True, tag="input", input_type="text")
    assert session.fill("#q", "widgets") == "filled #q"
    assert session.type_text("#q", "!") == "typed into #q"
    assert page.submits == []
    assert session.type_text("#q", "line\n").startswith("error:")
    assert page.typed == [("#q", "!")]


def test_submit_requires_the_approved_host(tmp_path: Path) -> None:
    session, page = _session(tmp_path)
    session.navigate("https://example.com/form")
    page.elements["#form"] = ElementInfo(
        found=True,
        tag="form",
        href="https://example.com/form",
    )
    page.elements["#remote"] = ElementInfo(
        found=True,
        tag="form",
        href="https://payments.example/charge",
    )
    mismatch = session.submit("#remote", "https://example.com/form")
    assert "payments.example" in mismatch
    assert page.submits == []
    sent = session.submit("#remote", "https://payments.example/charge")
    assert sent.startswith("submitted #remote")
    assert page.submits == ["#remote"]
    assert "payments.example" in session.hosts
    same = session.submit("#form", "https://example.com/form")
    assert same.startswith("submitted #form")


def test_screenshot_and_download_stay_in_the_output_directory(tmp_path: Path) -> None:
    session, page = _session(tmp_path)
    session.navigate("https://example.com")
    saved = session.screenshot("shots/page.png")
    assert saved == "saved shots/page.png"
    assert (tmp_path / "shots" / "page.png").read_bytes() == b"png"
    assert session.screenshot("../outside.png").startswith("error:")
    assert session.screenshot("/tmp/page.png").startswith("error:")
    downloaded = session.download("https://example.com/file.txt", "file.txt")
    assert downloaded.startswith("downloaded")
    assert page.downloads[0][0] == "https://example.com/file.txt"
    assert session.download("file:///tmp/secret", "x.bin").startswith("error:")
    page.download_size = DOWNLOAD_LIMIT + 1
    assert "20 MB" in session.download("https://example.com/big.bin", "big.bin")
    assert not (tmp_path / "big.bin").exists()
