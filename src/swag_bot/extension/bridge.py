"""Match a native-messaging request with the reply that arrives later.

The host's stdin loop and the agent thread share one bridge. ``request``
sends a message and waits. ``resolve`` wakes that wait from the stdin thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from swag_bot.errors import SwagError


class BridgeClosed(SwagError):
    """The extension disconnected while a request was waiting."""


class BridgeTimeout(SwagError):
    """The extension did not answer before the deadline."""


class _Waiter:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: dict[str, Any] | None = None


class PortBridge:
    """Thread-safe request map over a single native port."""

    def __init__(self, write: Callable[[Mapping[str, Any]], None]) -> None:
        self._write = write
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, _Waiter] = {}
        self._closed = False

    def send(self, payload: Mapping[str, Any]) -> None:
        """Write one message. Safe to call from the agent thread."""
        with self._write_lock:
            self._write(payload)

    def request(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float | None,
    ) -> dict[str, Any]:
        """Send ``payload`` with a new ``request_id`` and wait for ``resolve``."""
        request_id = uuid4().hex
        waiter = _Waiter()
        with self._pending_lock:
            if self._closed:
                raise BridgeClosed("the Chrome extension disconnected")
            self._pending[request_id] = waiter
        message = dict(payload)
        message["request_id"] = request_id
        try:
            self.send(message)
        except Exception:
            self._drop(request_id)
            raise
        if timeout is None:
            waiter.event.wait()
        elif not waiter.event.wait(timeout):
            self._drop(request_id)
            raise BridgeTimeout("the Chrome extension did not answer")
        if waiter.result is None:
            raise BridgeClosed("the Chrome extension disconnected")
        return waiter.result

    def resolve(self, request_id: str, result: Mapping[str, Any]) -> bool:
        """Wake the waiter for ``request_id``. Return False if it is unknown."""
        with self._pending_lock:
            waiter = self._pending.pop(request_id, None)
        if waiter is None:
            return False
        waiter.result = dict(result)
        waiter.event.set()
        return True

    def cancel_waiters(self) -> None:
        """Unblock every waiter with a denied, unsuccessful result.

        The port stays open so the next task can use it.
        """
        with self._pending_lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for waiter in waiters:
            waiter.result = {"ok": False, "approved": False, "error": "cancelled"}
            waiter.event.set()

    def close(self) -> None:
        """Unblock waiters because the port is gone."""
        with self._pending_lock:
            self._closed = True
            waiters = list(self._pending.values())
            self._pending.clear()
        for waiter in waiters:
            waiter.event.set()

    def _drop(self, request_id: str) -> None:
        with self._pending_lock:
            self._pending.pop(request_id, None)
