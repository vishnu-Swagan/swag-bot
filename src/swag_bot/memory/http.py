"""Stdlib HTTP for the agentmemory adapter. Tests inject their own request function."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from swag_bot.memory.errors import MemoryError
from swag_bot.memory.util import redact_secrets


class HTTPResponse:
    """Status and body. A transport returns this instead of raising for HTTP errors."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body


class HTTPTransport(Protocol):
    """One request. Connection failures raise ``MemoryError``."""

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        """Send ``body`` and return the status and bytes."""
        ...


class UrllibTransport:
    """``urllib`` implementation of ``HTTPTransport``."""

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured memory URL
                payload = response.read()
                status = int(getattr(response, "status", 200))
                return HTTPResponse(status, payload)
        except HTTPError as exc:
            payload = exc.read()
            return HTTPResponse(exc.code, payload)
        except URLError as exc:
            reason = redact_secrets(str(exc.reason))
            raise MemoryError(f"request to the memory server failed: {reason}") from exc
        except TimeoutError as exc:
            raise MemoryError("request to the memory server timed out") from exc
