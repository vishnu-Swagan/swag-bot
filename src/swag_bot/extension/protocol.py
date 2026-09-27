"""Chrome native messaging frames.

A message is a native-endian uint32 length followed by UTF-8 JSON. Chrome's
own sample uses ``struct.pack("I", ...)``. Messages larger than 1 MiB are
rejected. Nothing in this module writes to stdout except through the stream
the caller passes.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from typing import Any, BinaryIO, cast

from swag_bot.errors import SwagError

MAX_MESSAGE_BYTES = 1024 * 1024
_HEADER = struct.Struct("I")


class ProtocolError(SwagError):
    """The native messaging stream is not a sequence of JSON objects."""


def clip_text(value: str, limit: int) -> str:
    """Shorten ``value`` to ``limit`` characters. A short value is unchanged."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def encode_message(payload: Mapping[str, Any]) -> bytes:
    """Return one framed message. Raise ``ProtocolError`` if it is over 1 MiB."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_MESSAGE_BYTES:
        raise ProtocolError("native message exceeds 1 MiB")
    return _HEADER.pack(len(body)) + body


def write_message(stream: BinaryIO, payload: Mapping[str, Any]) -> None:
    """Write one framed message and flush."""
    stream.write(encode_message(payload))
    stream.flush()


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one framed message. ``None`` means the stream closed cleanly."""
    header = _read_exact(stream, _HEADER.size)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    if length <= 0 or length > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"native message length {length} is outside 1..{MAX_MESSAGE_BYTES}")
    body = _read_exact(stream, length)
    if body is None:
        raise ProtocolError("truncated native message")
    try:
        loaded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("native message is not UTF-8 JSON") from exc
    if not isinstance(loaded, dict):
        raise ProtocolError("native message must be a JSON object")
    return cast(dict[str, Any], loaded)


def _read_exact(stream: BinaryIO, length: int) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < length:
        piece = stream.read(length - len(chunks))
        if not piece:
            if not chunks:
                return None
            raise ProtocolError("truncated native message")
        chunks.extend(piece)
    return bytes(chunks)
