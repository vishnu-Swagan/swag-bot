"""Minisign (ed25519) public keys, secret keys, and signatures.

Minisign is the tool Arch Linux, Void, and Signify-compatible publishers
already use. A signature verifies offline: there is no transparency-log
round trip. Swag Bot writes the current prehashed form (algorithm ``ED``,
BLAKE2b-512, then Ed25519) so ``minisign -V`` accepts it, and it also
accepts legacy raw ``Ed`` signatures.

Password-encrypted secret keys (KDF ``Sc``) are recognized and refused.
Decrypt them with ``minisign -C -W`` or sign with the ``minisign`` CLI.
Verification never needs the secret key.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from swag_bot.plugins.ed25519 import public_key_from_seed, sign, verify

_SIGALG = b"Ed"
_SIGALG_HASHED = b"ED"
_KDF_NONE = b"\x00\x00"
_KDF_SCRYPT = b"Sc"
_CHKALG = b"B2"
_COMMENT_PREFIX = "untrusted comment: "
_TRUSTED_PREFIX = "trusted comment: "
_PUBLIC_COMMENT = "minisign public key "
_SECRET_COMMENT = "swag bot unencrypted minisign secret key"
_SIGNATURE_COMMENT = "signature from minisign secret key"
_SALT_LEN = 32
_KEY_ID_LEN = 8
_PUBLIC_LEN = 32
_SEED_LEN = 32
_SIG_LEN = 64
_CHK_LEN = 32


class MinisignError(ValueError):
    """A minisign key or signature could not be parsed or verified."""


@dataclass(frozen=True)
class PublicKey:
    """A minisign public key (algorithm ``Ed``, 8-byte id, 32-byte key)."""

    key_id: bytes
    public: bytes

    @property
    def key_id_hex(self) -> str:
        """Key id as minisign prints it: 16 uppercase hex digits, little-endian."""
        return f"{int.from_bytes(self.key_id, 'little'):016X}"

    def raw_bytes(self) -> bytes:
        """42-byte public-key struct."""
        return _SIGALG + self.key_id + self.public

    def b64_line(self) -> str:
        """Single base64 line. This is what ``minisign -P`` expects."""
        return base64.b64encode(self.raw_bytes()).decode("ascii")

    def file_text(self) -> str:
        """Public-key file contents, including the untrusted comment."""
        comment = f"{_COMMENT_PREFIX}{_PUBLIC_COMMENT}{self.key_id_hex}\n"
        return comment + self.b64_line() + "\n"


@dataclass(frozen=True)
class SecretKey:
    """Unencrypted minisign secret key. The seed is 32 bytes."""

    key_id: bytes
    seed: bytes
    public: bytes

    def public_key(self) -> PublicKey:
        return PublicKey(self.key_id, self.public)

    def file_text(self) -> str:
        """Unencrypted secret-key file. Mode ``0600`` when written to disk."""
        checksum = hashlib.blake2b(
            _SIGALG + self.key_id + self.seed + self.public,
            digest_size=_CHK_LEN,
        ).digest()
        raw = b"".join(
            (
                _SIGALG,
                _KDF_NONE,
                _CHKALG,
                bytes(_SALT_LEN),
                bytes(8),
                bytes(8),
                self.key_id,
                self.seed + self.public,
                checksum,
            )
        )
        if len(raw) != 158:
            raise MinisignError("secret key struct was not 158 bytes")
        comment = f"{_COMMENT_PREFIX}{_SECRET_COMMENT}\n"
        return comment + base64.b64encode(raw).decode("ascii") + "\n"


@dataclass(frozen=True)
class Signature:
    """One ``.minisig`` file."""

    algorithm: bytes
    key_id: bytes
    signature: bytes
    trusted_comment: str
    global_signature: bytes
    untrusted_comment: str = _SIGNATURE_COMMENT

    @property
    def prehashed(self) -> bool:
        """True for the modern BLAKE2b-512 prehash (algorithm ``ED``)."""
        return self.algorithm == _SIGALG_HASHED

    def file_text(self) -> str:
        """Four-line minisign signature file."""
        struct = self.algorithm + self.key_id + self.signature
        lines = (
            f"{_COMMENT_PREFIX}{self.untrusted_comment}",
            base64.b64encode(struct).decode("ascii"),
            f"{_TRUSTED_PREFIX}{self.trusted_comment}",
            base64.b64encode(self.global_signature).decode("ascii"),
        )
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of checking one signature. ``reason`` is empty when ``ok`` is true."""

    ok: bool
    key_id: str
    reason: str


def generate_keypair() -> tuple[SecretKey, PublicKey]:
    """Random key id and seed. The public key is derived from the seed."""
    seed = secrets.token_bytes(_SEED_LEN)
    key_id = secrets.token_bytes(_KEY_ID_LEN)
    public = public_key_from_seed(seed)
    secret = SecretKey(key_id, seed, public)
    return secret, secret.public_key()


def write_keypair(directory: Path, *, force: bool = False) -> tuple[Path, Path]:
    """Write ``minisign.pub`` and ``minisign.key`` into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    public_path = directory / "minisign.pub"
    secret_path = directory / "minisign.key"
    if not force and (public_path.exists() or secret_path.exists()):
        raise MinisignError(f"key files already exist in {directory}; pass force to overwrite")
    secret, public = generate_keypair()
    secret_path.write_text(secret.file_text(), encoding="utf-8")
    os.chmod(secret_path, 0o600)
    public_path.write_text(public.file_text(), encoding="utf-8")
    return secret_path, public_path


def load_public_key(text: str) -> PublicKey:
    """Parse a public-key file or the raw base64 line from ``minisign -P``."""
    line = _key_line(text)
    try:
        raw = base64.b64decode(line, validate=True)
    except ValueError as exc:
        raise MinisignError("public key is not valid base64") from exc
    if len(raw) != 42 or raw[:2] != _SIGALG:
        raise MinisignError("public key is not a minisign Ed25519 key")
    return PublicKey(raw[2:10], raw[10:42])


def load_secret_key(text: str) -> SecretKey:
    """Parse an unencrypted minisign secret key written by Swag Bot or ``minisign -G -W``."""
    line = _key_line(text)
    try:
        raw = base64.b64decode(line, validate=True)
    except ValueError as exc:
        raise MinisignError("secret key is not valid base64") from exc
    if len(raw) != 158:
        raise MinisignError("secret key has the wrong length")
    if raw[:2] != _SIGALG:
        raise MinisignError("unsupported secret-key algorithm")
    if raw[2:4] == _KDF_SCRYPT:
        raise MinisignError(
            "secret key is password-encrypted; decrypt it with 'minisign -C -W' "
            "or sign with the minisign CLI"
        )
    if raw[2:4] != _KDF_NONE:
        raise MinisignError("unsupported secret-key derivation")
    if raw[4:6] != _CHKALG:
        raise MinisignError("unsupported secret-key checksum")
    key_id = raw[54:62]
    secret_material = raw[62:126]
    seed = secret_material[:32]
    public = secret_material[32:64]
    derived = public_key_from_seed(seed)
    if derived != public:
        raise MinisignError("secret key does not match its embedded public key")
    return SecretKey(key_id, seed, public)


def load_signature(text: str) -> Signature:
    """Parse a ``.minisig`` file."""
    lines = [line.strip("\r") for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        raise MinisignError(
            "signature file needs an untrusted comment, a signature, a trusted comment, "
            "and a global signature"
        )
    if not lines[0].startswith(_COMMENT_PREFIX):
        raise MinisignError("signature file must start with 'untrusted comment: '")
    if not lines[2].startswith(_TRUSTED_PREFIX):
        raise MinisignError("signature file is missing 'trusted comment: '")
    try:
        struct = base64.b64decode(lines[1], validate=True)
        global_sig = base64.b64decode(lines[3], validate=True)
    except ValueError as exc:
        raise MinisignError("signature file is not valid base64") from exc
    if len(struct) != 74:
        raise MinisignError("signature struct has the wrong length")
    algorithm = struct[:2]
    if algorithm not in {_SIGALG, _SIGALG_HASHED}:
        raise MinisignError("unsupported signature algorithm")
    if len(global_sig) != _SIG_LEN:
        raise MinisignError("global signature has the wrong length")
    trusted = lines[2][len(_TRUSTED_PREFIX) :].rstrip(" \r\n")
    if not trusted:
        raise MinisignError("trusted comment is empty")
    if any(ord(char) < 32 and char != "\t" for char in trusted):
        raise MinisignError("trusted comment contains control characters")
    return Signature(
        algorithm=algorithm,
        key_id=struct[2:10],
        signature=struct[10:74],
        trusted_comment=trusted,
        global_signature=global_sig,
        untrusted_comment=lines[0][len(_COMMENT_PREFIX) :],
    )


def sign_message(
    message: bytes,
    secret: SecretKey,
    *,
    trusted_comment: str | None = None,
    filename: str = "plugin.bundle",
    legacy: bool = False,
) -> Signature:
    """Sign ``message``. The default is minisign's prehashed ``ED`` form."""
    if trusted_comment is not None and ("\n" in trusted_comment or "\r" in trusted_comment):
        raise MinisignError("trusted comment must be a single line")
    prehash = not legacy
    payload = _signed_payload(message, prehash=prehash)
    file_sig = sign(secret.seed, payload)
    if trusted_comment is None:
        stamp = _timestamp()
        suffix = "\thashed" if prehash else ""
        trusted_comment = f"timestamp:{stamp}\tfile:{filename}{suffix}"
    global_sig = sign(secret.seed, file_sig + trusted_comment.encode("utf-8"))
    return Signature(
        algorithm=_SIGALG_HASHED if prehash else _SIGALG,
        key_id=secret.key_id,
        signature=file_sig,
        trusted_comment=trusted_comment,
        global_signature=global_sig,
    )


def verify_message(message: bytes, signature: Signature, public: PublicKey) -> VerifyResult:
    """Check the file signature and the trusted-comment signature."""
    key_id = public.key_id_hex
    if signature.key_id != public.key_id:
        return VerifyResult(
            ok=False,
            key_id=key_id,
            reason=(
                f"signature key id {signature_key_id(signature)} does not match "
                f"public key {key_id}"
            ),
        )
    payload = _signed_payload(message, prehash=signature.prehashed)
    if not verify(public.public, payload, signature.signature):
        return VerifyResult(ok=False, key_id=key_id, reason="signature verification failed")
    comment_message = signature.signature + signature.trusted_comment.encode("utf-8")
    if not verify(public.public, comment_message, signature.global_signature):
        return VerifyResult(
            ok=False,
            key_id=key_id,
            reason="trusted comment signature verification failed",
        )
    return VerifyResult(ok=True, key_id=key_id, reason="")


def signature_key_id(signature: Signature) -> str:
    """Key id printed the same way as on a public key."""
    return f"{int.from_bytes(signature.key_id, 'little'):016X}"


def _signed_payload(message: bytes, *, prehash: bool) -> bytes:
    if not prehash:
        return message
    return hashlib.blake2b(message, digest_size=64).digest()


def _key_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise MinisignError("key is empty")
    for line in lines:
        if line.startswith(_COMMENT_PREFIX):
            continue
        return line
    raise MinisignError("key file has no base64 line")


def _timestamp() -> int:
    return int(time.time())
