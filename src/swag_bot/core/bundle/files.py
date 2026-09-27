"""Workspace snapshots and unified diffs for a run bundle.

File bytes are hashed with SHA-256 after redaction. The canonical tree JSON
matches the undo ledger (``$SWAG_HOME/undo``): sorted keys, no extra spaces.
A blob hash equals an undo object hash when redaction did not change the
bytes. Tree hashes also include directory entries and file modes, so they
match an undo tree only when those agree too.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swag_bot.core.bundle.redact import redact_text
from swag_bot.core.bundle.spec import (
    ARTIFACT_FILES,
    BLOB_CHAR_LIMIT,
    DIFF_CHAR_LIMIT,
    SKIP_TOP_DIRS,
    UNDO_ALIGNMENT,
)


@dataclass
class Snapshot:
    """One content-addressed view of a workdir."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    blobs: dict[str, str] = field(default_factory=dict)
    tree: str = ""


def sha256_text(text: str) -> str:
    """Hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_hash(entries: list[dict[str, Any]]) -> str:
    """Hash the undo-style canonical JSON of ``entries``."""
    payload = json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def snapshot_workdir(root: Path) -> Snapshot:
    """Capture regular files under ``root``. Secrets in the text are redacted."""
    workdir = root.resolve()
    entries: list[dict[str, Any]] = []
    blobs: dict[str, str] = {}
    if not workdir.exists():
        return Snapshot(tree=tree_hash(entries))
    for dirpath, dirnames, filenames in os.walk(workdir, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            child = current / name
            if _skip(workdir, child):
                continue
            if child.is_symlink():
                continue
            kept.append(name)
            entries.append(_dir_entry(workdir, child))
        dirnames[:] = kept
        for name in filenames:
            child = current / name
            if _skip(workdir, child) or child.is_symlink():
                continue
            entry, blob = _file_entry(workdir, child)
            entries.append(entry)
            digest = entry.get("hash")
            if isinstance(digest, str) and blob is not None:
                blobs[digest] = blob
    entries.sort(key=lambda item: str(item.get("path", "")))
    return Snapshot(entries=entries, blobs=blobs, tree=tree_hash(entries))


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[dict[str, Any]]:
    """Unified diffs for files that were added, edited, or removed."""
    before_files = _files(before)
    after_files = _files(after)
    changes: list[dict[str, Any]] = []
    for path in sorted(set(before_files) | set(after_files)):
        previous = before_files.get(path)
        current = after_files.get(path)
        if previous == current:
            continue
        before_text = "" if previous is None else before.blobs.get(previous, "")
        after_text = "" if current is None else after.blobs.get(current, "")
        if previous is None:
            op = "add"
        elif current is None:
            op = "delete"
        else:
            op = "modify"
        changes.append(
            {
                "path": path,
                "op": op,
                "before_sha256": previous,
                "after_sha256": current,
                "diff": _unified(path, before_text, after_text),
            }
        )
    return changes


def restore_files(root: Path, entries: list[dict[str, Any]], blobs: dict[str, str]) -> None:
    """Write file entries into ``root``. Missing blobs are skipped."""
    root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry.get("kind") != "file":
            continue
        digest = entry.get("hash")
        rel = entry.get("path")
        if not isinstance(digest, str) or not isinstance(rel, str):
            continue
        if _unsafe(rel):
            continue
        text = blobs.get(digest)
        if text is None:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def load_blobs(bundle_root: Path) -> dict[str, str]:
    """Read ``files/objects`` from a bundle directory."""
    objects = bundle_root / "files" / "objects"
    found: dict[str, str] = {}
    if not objects.is_dir():
        return found
    for path in objects.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(objects).as_posix()
        digest = relative.replace("/", "")
        found[digest] = path.read_text(encoding="utf-8")
    return found


def trees_document(before: Snapshot, after: Snapshot) -> dict[str, Any]:
    """JSON document stored at ``files/trees.json``."""
    return {
        "aligned_with": UNDO_ALIGNMENT,
        "note": (
            "Blob hashes are SHA-256 of the redacted UTF-8 bytes. "
            "The undo ledger hashes the original bytes under $SWAG_HOME/undo/objects. "
            "Those hashes match when redaction changed nothing. "
            "Tree JSON uses the same canonical encoding as the undo snapshot."
        ),
        "before": {"tree": before.tree, "entries": before.entries},
        "after": {"tree": after.tree, "entries": after.entries},
    }


def _files(snapshot: Snapshot) -> dict[str, str]:
    found: dict[str, str] = {}
    for entry in snapshot.entries:
        if entry.get("kind") != "file":
            continue
        path = entry.get("path")
        digest = entry.get("hash")
        if isinstance(path, str) and isinstance(digest, str):
            found[path] = digest
    return found


def _file_entry(workdir: Path, path: Path) -> tuple[dict[str, Any], str | None]:
    rel = path.relative_to(workdir).as_posix()
    mode = stat.S_IMODE(path.lstat().st_mode)
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"kind": "special", "mode": mode, "path": rel, "detail": str(exc)}, None
    if b"\x00" in data[:1024]:
        return {"kind": "special", "mode": mode, "path": rel, "detail": "binary"}, None
    truncated = len(data) > BLOB_CHAR_LIMIT
    raw = data[:BLOB_CHAR_LIMIT].decode("utf-8", errors="replace")
    text = redact_text(raw)
    digest = sha256_text(text)
    entry: dict[str, Any] = {"hash": digest, "kind": "file", "mode": mode, "path": rel}
    if truncated:
        entry["truncated"] = True
    return entry, text


def _dir_entry(workdir: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(workdir).as_posix()
    mode = stat.S_IMODE(path.lstat().st_mode)
    return {"kind": "dir", "mode": mode, "path": rel}


def _skip(workdir: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(workdir)
    except ValueError:
        return True
    parts = relative.parts
    if not parts:
        return False
    if parts[0] in SKIP_TOP_DIRS:
        return True
    return len(parts) == 1 and relative.name in ARTIFACT_FILES


def _unsafe(relative: str) -> bool:
    if not relative or relative.startswith("/") or relative.startswith("\\"):
        return True
    return ".." in Path(relative).parts


def _unified(path: str, before: str, after: str) -> str:
    import difflib

    lines = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    text = "\n".join(lines)
    if len(text) <= DIFF_CHAR_LIMIT:
        return text
    return text[: DIFF_CHAR_LIMIT - 3] + "..."
