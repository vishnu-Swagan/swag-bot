"""Headless Chromium against a local page.

Skipped when Playwright is not installed or Chromium cannot be launched.
CI does not install the browser extra, so this test does not run there.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from swag_bot.browser.session import BrowserSession, host_key


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/file.txt"):
            body = b"hello-from-download"
            self._send(body, "text/plain")
            return
        if self.path.startswith("/next"):
            body = (
                b"<html><head><title>Next</title></head>"
                b"<body><p id='there'>Second page</p></body></html>"
            )
        elif self.path.startswith("/submit"):
            body = (
                b"<html><head><title>Sent</title></head>"
                b"<body><p id='sent'>Form sent</p></body></html>"
            )
        else:
            body = (
                b"<html><head><title>Swag Test</title></head><body>"
                b"<p id='price'>Price: 42</p>"
                b"<a id='same' href='/next'>next</a>"
                b"<a id='away' href='https://example.com/'>away</a>"
                b"<form id='form' action='/submit' method='get'>"
                b"<input id='q' name='q' value='' />"
                b"<button id='go' type='submit'>Go</button>"
                b"</form></body></html>"
            )
        self._send(body, "text/html; charset=utf-8")

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_headless_browser_reads_clicks_submits_and_downloads(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    from swag_bot.browser.playwright_page import PlaywrightPage

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}/"
    page = None
    try:
        try:
            page = PlaywrightPage()
        except Exception as exc:
            pytest.skip(f"headless Chromium is not available: {exc}")
        session = BrowserSession(page, tmp_path)
        opened = session.navigate(base)
        assert "new domain" in opened
        assert "Swag Test" in session.snapshot()
        assert "Price: 42" in session.extract("#price")

        refused = session.click("#away")
        assert "new domain" in refused
        assert host_key(page.url()) == host_key(base)

        assert session.click("#same").startswith("clicked")
        assert "Second page" in session.extract("#there")

        assert "known domain" in session.navigate(base)
        assert session.fill("#q", "widgets") == "filled #q"
        assert "submit" in session.click("#go")
        submitted = session.submit("#go", base)
        assert submitted.startswith("submitted")
        assert "sent" in page.url() or "submit" in page.url()

        assert session.screenshot("shots/page.png") == "saved shots/page.png"
        assert (tmp_path / "shots" / "page.png").stat().st_size > 8
        downloaded = session.download(f"{base}file.txt", "file.txt")
        assert downloaded.startswith("downloaded")
        assert (tmp_path / "file.txt").read_bytes() == b"hello-from-download"
    finally:
        if page is not None:
            page.close()
        server.shutdown()
        thread.join(timeout=5)
