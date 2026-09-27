"""Pure Ed25519, matching libsodium ``crypto_sign`` (RFC 8032, no domain prefix).

This is the signature primitive minisign uses. It is not constant-time.
Plugin signing is a local, one-shot operation; do not use this module for
online protocols that need a side-channel-hardened implementation.
"""

from __future__ import annotations

import hashlib

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)
_Point = tuple[int, int]


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _xrecover(y: int) -> int:
    """Even x for the curve point with this y. Raises ``ValueError`` if none exists."""
    yy = y * y % _P
    xx = (yy - 1) * pow(_D * yy + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = x * _I % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("point is not on the curve")
    if x & 1:
        x = _P - x
    return x


def _decode_point(data: bytes) -> _Point | None:
    if len(data) != 32:
        return None
    raw = int.from_bytes(data, "little")
    sign = (raw >> 255) & 1
    y = raw & ((1 << 255) - 1)
    if y >= _P:
        return None
    try:
        x = _xrecover(y)
    except ValueError:
        return None
    if x == 0 and sign:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x, y


def _encode_point(point: _Point) -> bytes:
    x, y = point
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _edwards_add(p: _Point, q: _Point) -> _Point:
    x1, y1 = p
    x2, y2 = q
    product = _D * x1 * x2 * y1 * y2 % _P
    x3 = (x1 * y2 + y1 * x2) * pow((1 + product) % _P, _P - 2, _P) % _P
    y3 = (y1 * y2 + x1 * x2) * pow((1 - product) % _P, _P - 2, _P) % _P
    return x3, y3


def _scalarmult(point: _Point, scalar: int) -> _Point:
    result: _Point = (0, 1)
    addend = point
    value = scalar
    while value > 0:
        if value & 1:
            result = _edwards_add(result, addend)
        addend = _edwards_add(addend, addend)
        value >>= 1
    return result


_B: _Point = (_xrecover((4 * pow(5, _P - 2, _P)) % _P), (4 * pow(5, _P - 2, _P)) % _P)


def _expand(seed: bytes) -> tuple[int, bytes]:
    digest = _sha512(seed)
    clamped = bytearray(digest[:32])
    clamped[0] &= 248
    clamped[31] &= 63
    clamped[31] |= 64
    return int.from_bytes(clamped, "little"), digest[32:]


def public_key_from_seed(seed: bytes) -> bytes:
    """32-byte public key for a 32-byte seed."""
    if len(seed) != 32:
        raise ValueError("ed25519 seed must be 32 bytes")
    scalar, _prefix = _expand(seed)
    return _encode_point(_scalarmult(_B, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    """Detached 64-byte signature of ``message`` under ``seed``."""
    if len(seed) != 32:
        raise ValueError("ed25519 seed must be 32 bytes")
    scalar, prefix = _expand(seed)
    public = _encode_point(_scalarmult(_B, scalar))
    nonce = int.from_bytes(_sha512(prefix + message), "little") % _L
    commitment = _encode_point(_scalarmult(_B, nonce))
    challenge = int.from_bytes(_sha512(commitment + public + message), "little") % _L
    proof = (nonce + challenge * scalar) % _L
    return commitment + proof.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True when ``signature`` is a valid signature of ``message`` by ``public``."""
    if len(public) != 32 or len(signature) != 64:
        return False
    commitment = _decode_point(signature[:32])
    point = _decode_point(public)
    if commitment is None or point is None:
        return False
    proof = int.from_bytes(signature[32:], "little")
    if proof >= _L:
        return False
    challenge = int.from_bytes(_sha512(signature[:32] + public + message), "little") % _L
    left = _scalarmult(_B, proof)
    right = _edwards_add(commitment, _scalarmult(point, challenge))
    return left == right
