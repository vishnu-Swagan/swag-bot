"""Minisign key files and signatures, including interop with the minisign CLI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from swag_bot.plugins.minisign import (
    MinisignError,
    generate_keypair,
    load_public_key,
    load_secret_key,
    load_signature,
    sign_message,
    verify_message,
    write_keypair,
)


def test_round_trip_prehashed_and_legacy(tmp_path: Path) -> None:
    secret_path, public_path = write_keypair(tmp_path)
    assert oct(secret_path.stat().st_mode & 0o777) == "0o600"
    secret = load_secret_key(secret_path.read_text(encoding="utf-8"))
    public = load_public_key(public_path.read_text(encoding="utf-8"))
    message = b"hello swag\n"
    for legacy in (False, True):
        signature = sign_message(message, secret, filename="msg.txt", legacy=legacy)
        parsed = load_signature(signature.file_text())
        result = verify_message(message, parsed, public)
        assert result.ok, result.reason
        assert result.key_id == public.key_id_hex
        tampered = verify_message(message + b"x", parsed, public)
        assert not tampered.ok
        assert tampered.reason == "signature verification failed"


def test_encrypted_secret_key_is_refused() -> None:
    _secret, public = generate_keypair()
    # 158-byte struct with KDF "Sc" and garbage after the algorithm fields.
    raw = bytearray(158)
    raw[0:2] = b"Ed"
    raw[2:4] = b"Sc"
    raw[4:6] = b"B2"
    import base64

    text = "untrusted comment: encrypted\n" + base64.b64encode(bytes(raw)).decode("ascii") + "\n"
    with pytest.raises(MinisignError, match="password-encrypted"):
        load_secret_key(text)
    assert public.b64_line()


def test_comment_substitution_fails() -> None:
    secret, public = generate_keypair()
    signature = sign_message(b"payload", secret, trusted_comment="timestamp:1\tfile:a\thashed")
    forged = signature.file_text().replace("timestamp:1", "timestamp:9")
    parsed = load_signature(forged)
    result = verify_message(b"payload", parsed, public)
    assert not result.ok
    assert "comment" in result.reason


def test_official_minisign_accepts_our_signature(tmp_path: Path) -> None:
    binary = shutil.which("minisign")
    if binary is None:
        pytest.skip("minisign is not installed")
    secret_path, public_path = write_keypair(tmp_path)
    message_path = tmp_path / "msg.txt"
    message = b"hello swag\n"
    message_path.write_bytes(message)
    secret = load_secret_key(secret_path.read_text(encoding="utf-8"))
    public = load_public_key(public_path.read_text(encoding="utf-8"))
    signature = sign_message(
        message,
        secret,
        filename="msg.txt",
        trusted_comment="timestamp:1\tfile:msg.txt\thashed",
    )
    signature_path = tmp_path / "msg.txt.minisig"
    signature_path.write_text(signature.file_text(), encoding="utf-8")
    verified = subprocess.run(
        [binary, "-V", "-p", str(public_path), "-m", str(message_path), "-x", str(signature_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert "Signature and comment signature verified" in verified.stdout

    official = tmp_path / "official.minisig"
    signed = subprocess.run(
        [
            binary,
            "-S",
            "-s",
            str(secret_path),
            "-m",
            str(message_path),
            "-x",
            str(official),
            "-t",
            "timestamp:1\tfile:msg.txt\thashed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert signed.returncode == 0, signed.stderr
    result = verify_message(message, load_signature(official.read_text(encoding="utf-8")), public)
    assert result.ok, result.reason
