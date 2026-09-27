"""Native messaging host process.

Chrome starts this program when the side panel connects and stops it when
the port closes. Stdout is reserved for framed messages. Diagnostics go to
stderr.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Mapping
from typing import Any, BinaryIO

from swag_bot import __version__
from swag_bot.extension.bridge import PortBridge
from swag_bot.extension.ids import HOST_NAME, PROTOCOL_VERSION
from swag_bot.extension.protocol import ProtocolError, read_message, write_message
from swag_bot.extension.session import Runner, run_session


class HostSession:
    """One native port. At most one task runs at a time."""

    def __init__(
        self,
        bridge: PortBridge,
        *,
        runner: Runner | None = None,
    ) -> None:
        self._bridge = bridge
        self._runner = runner
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._run_id: str | None = None

    def handle(self, message: Mapping[str, Any]) -> None:
        """Dispatch one client message. Protocol mistakes are reported, not raised."""
        kind = message.get("type")
        if kind == "hello":
            self._bridge.send(
                {
                    "type": "hello",
                    "version": __version__,
                    "host": HOST_NAME,
                    "protocol": PROTOCOL_VERSION,
                }
            )
            return
        if kind == "ping":
            self._bridge.send({"type": "pong", "version": __version__})
            return
        if kind == "run":
            self._start(message)
            return
        if kind == "approval":
            self._resolve(message, approved=message.get("approved") is True)
            return
        if kind == "tab_result":
            self._resolve_tab(message)
            return
        if kind == "cancel":
            self._cancel_run()
            return
        run_id = message.get("id")
        self._error(
            "unknown message type",
            run_id if isinstance(run_id, str) else None,
        )

    def shutdown(self) -> None:
        """Unblock a task that is waiting on the extension."""
        self._cancel.set()
        self._bridge.close()

    def _start(self, message: Mapping[str, Any]) -> None:
        run_id = message.get("id")
        label = run_id if isinstance(run_id, str) else None
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._error("a task is already running", label)
                return
            cancel = threading.Event()
            self._cancel = cancel
            self._run_id = label

            def worker() -> None:
                try:
                    run_session(message, self._bridge, runner=self._runner, cancel=cancel)
                finally:
                    with self._lock:
                        if self._cancel is cancel:
                            self._thread = None

            thread = threading.Thread(target=worker, name="swag-extension-run", daemon=True)
            self._thread = thread
        thread.start()

    def _cancel_run(self) -> None:
        with self._lock:
            self._cancel.set()
        self._bridge.cancel_waiters()

    def _resolve(self, message: Mapping[str, Any], *, approved: bool) -> None:
        request_id = message.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            self._error("approval is missing request_id", None)
            return
        self._bridge.resolve(request_id, {"approved": approved, "ok": True})

    def _resolve_tab(self, message: Mapping[str, Any]) -> None:
        request_id = message.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            self._error("tab_result is missing request_id", None)
            return
        result: dict[str, Any] = {"ok": message.get("ok") is True}
        for key in ("error", "title", "url", "content", "detail", "selector"):
            value = message.get(key)
            if isinstance(value, str):
                result[key] = value[:20_000]
        self._bridge.resolve(request_id, result)

    def _error(self, text: str, run_id: str | None) -> None:
        payload: dict[str, Any] = {"type": "error", "message": text}
        if run_id:
            payload["id"] = run_id
        self._bridge.send(payload)


def serve(
    stdin: BinaryIO,
    stdout: BinaryIO,
    *,
    runner: Runner | None = None,
) -> None:
    """Read native messages until the browser closes the pipe."""
    bridge = PortBridge(lambda payload: write_message(stdout, payload))
    session = HostSession(bridge, runner=runner)
    while True:
        try:
            message = read_message(stdin)
        except ProtocolError as exc:
            _report(stdout, str(exc))
            session.shutdown()
            return
        if message is None:
            session.shutdown()
            return
        try:
            session.handle(message)
        except ProtocolError as exc:
            _report(stdout, str(exc))


def main() -> None:
    """Entry point Chrome launches. Stdout is the native messaging pipe."""
    serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()


def _report(stdout: BinaryIO, message: str) -> None:
    try:
        write_message(stdout, {"type": "error", "message": message})
    except Exception:
        print(message, file=sys.stderr)
