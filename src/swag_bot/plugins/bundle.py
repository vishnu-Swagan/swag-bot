"""Canonical bytes for a plugin directory.

Publishers sign this byte string, not a tar archive. The walk is sorted and
skips the signature directory, so two machines produce the same digest and
the signature does not have to cover itself.

Format (``SWAG-PLUGIN-BUNDLE/1``):

- ASCII magic ``SWAG-PLUGIN-BUNDLE/1`` and a newline
- for each file, in ascending relative POSIX path order:
  the path as UTF-8, a newline, the decimal size, a newline, the raw bytes

``.git/``, ``__pycache__/``, ``.swag-gallery/``, ``.DS_Store``, and ``*.pyc``
are omitted. Symbolic links are rejected.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from swag_bot.plugins.errors import PluginError

_MAGIC = b"SWAG-PLUGIN-BUNDLE/1\n"
_SKIP_DIRS = frozenset({".git", "__pycache__", ".swag-gallery"})
_SKIP_FILES = frozenset({".DS_Store"})
_MAX_BUNDLE = 32 * 1024 * 1024

BUNDLE_MAGIC = "SWAG-PLUGIN-BUNDLE/1"
GALLERY_META_DIR = ".swag-gallery"


def plugin_files(root: Path) -> list[Path]:
    """Regular files that belong in the signed bundle, in path order."""
    base = root.expanduser().resolve()
    if not base.is_dir():
        raise PluginError(f"plugin source is not a directory: {root}")
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in sorted(dirnames):
            if name in _SKIP_DIRS:
                continue
            path = current / name
            if path.is_symlink():
                raise PluginError(f"symlink is not allowed in a signed plugin: {_rel(base, path)}")
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            if name in _SKIP_FILES or name.endswith(".pyc"):
                continue
            path = current / name
            if path.is_symlink():
                raise PluginError(f"symlink is not allowed in a signed plugin: {_rel(base, path)}")
            if path.is_file():
                found.append(path)
    found.sort(key=lambda path: _rel(base, path))
    return found


def canonical_bundle(root: Path) -> bytes:
    """Deterministic bundle bytes for ``root``."""
    base = root.expanduser().resolve()
    chunks: list[bytes] = [_MAGIC]
    total = len(_MAGIC)
    for path in plugin_files(base):
        relative = _rel(base, path)
        if "\n" in relative or "\r" in relative:
            raise PluginError(f"plugin path contains a newline: {relative}")
        data = path.read_bytes()
        header = f"{relative}\n{len(data)}\n".encode()
        total += len(header) + len(data)
        if total > _MAX_BUNDLE:
            raise PluginError(f"plugin bundle exceeds {_MAX_BUNDLE} bytes")
        chunks.append(header)
        chunks.append(data)
    return b"".join(chunks)


def bundle_digest(bundle: bytes) -> str:
    """Lowercase hex SHA-256 of a canonical bundle."""
    return hashlib.sha256(bundle).hexdigest()


def _rel(base: Path, path: Path) -> str:
    return path.relative_to(base).as_posix()
