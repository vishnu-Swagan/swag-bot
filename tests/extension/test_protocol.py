"""Native messaging frames."""

from __future__ import annotations

import io

import pytest

from swag_bot.extension.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    clip_text,
    encode_message,
    read_message,
    write_message,
)


def test_round_trip() -> None:
    stream = io.BytesIO()
    write_message(stream, {"type": "hello", "text": "café"})
    stream.seek(0)
    assert read_message(stream) == {"type": "hello", "text": "café"}
    assert read_message(stream) is None


def test_rejects_non_object() -> None:
    body = b"[1, 2]"
    stream = io.BytesIO(encode_raw(body))
    with pytest.raises(ProtocolError, match="JSON object"):
        read_message(stream)


def test_rejects_oversize_length() -> None:
    stream = io.BytesIO(encode_raw(b"{}", length=MAX_MESSAGE_BYTES + 1))
    with pytest.raises(ProtocolError, match="length"):
        read_message(stream)


def test_rejects_truncated_body() -> None:
    stream = io.BytesIO(encode_raw(b"{", length=8))
    with pytest.raises(ProtocolError, match="truncated"):
        read_message(stream)


def test_encode_refuses_huge_payload() -> None:
    with pytest.raises(ProtocolError, match="1 MiB"):
        encode_message({"type": "run", "goal": "x" * (MAX_MESSAGE_BYTES + 1)})


def test_clip_text_marks_the_cut() -> None:
    assert clip_text("abcdef", 6) == "abcdef"
    assert clip_text("abcdef", 5) == "ab..."


def encode_raw(body: bytes, length: int | None = None) -> bytes:
    import struct

    size = len(body) if length is None else length
    return struct.pack("I", size) + body


def test_partial_header_is_truncated() -> None:
    stream = io.BytesIO(b"\x01\x00")
    with pytest.raises(ProtocolError, match="truncated"):
        read_message(stream)


def test_invalid_json() -> None:
    stream = io.BytesIO(encode_raw(b"not-json"))
    with pytest.raises(ProtocolError, match="JSON"):
        read_message(stream)


def test_empty_stream() -> None:
    assert read_message(io.BytesIO()) is None
