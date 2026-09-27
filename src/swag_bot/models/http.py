"""Small HTTP helper for the Ollama client. Stdlib only, so the base install stays light."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from swag_bot.models.errors import ModelError
from swag_bot.models.keys import redact_secrets


class HTTPResponse:
    """Status and body from one non-streaming request."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class HTTPTransport(Protocol):
    """What ``OllamaClient`` needs. Tests pass a fake."""

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        """Send one request and return the full body."""
        ...

    def stream(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Iterator[bytes]:
        """Yield raw body chunks as they arrive. One chunk is typically one line."""
        ...


class UrllibTransport:
    """``urllib`` transport. ``stream`` yields each line from the socket."""

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        try:
            with self._open(method, url, body, headers, timeout) as response:
                payload = response.read()
                status = int(getattr(response, "status", 200))
                return HTTPResponse(status, payload)
        except HTTPError as exc:
            payload = exc.read()
            return HTTPResponse(exc.code, payload)
        except URLError as exc:
            reason = redact_secrets(str(exc.reason))
            raise ModelError(f"request to {url} failed: {reason}") from exc
        except TimeoutError as exc:
            raise ModelError(f"request to {url} timed out") from exc

    def stream(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Iterator[bytes]:
        try:
            response = self._open(method, url, body, headers, timeout)
        except HTTPError as exc:
            payload = exc.read()
            raise ModelError(
                redact_secrets(f"HTTP {exc.code} from {url}: {payload.decode('utf-8', 'replace')}")
            ) from exc
        except URLError as exc:
            reason = redact_secrets(str(exc.reason))
            raise ModelError(f"request to {url} failed: {reason}") from exc
        except TimeoutError as exc:
            raise ModelError(f"request to {url} timed out") from exc
        try:
            while True:
                line = response.readline()
                if not line:
                    break
                yield line
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()

    def _open(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        request = Request(url, data=body, headers=dict(headers), method=method)
        return urlopen(request, timeout=timeout)  # noqa: S310 - host is the configured Ollama URL
