"""Content-addressed snapshots of a workspace directory.

Blobs are stored by SHA-256, the same idea as git objects, without calling
git and without writing inside the workspace. A later snapshot of an
unchanged file stores the hash again and does not copy the bytes.

The undo ledger keeps this store outside the workdir. A shell command that
deletes files in the workdir cannot delete the blobs that would restore them.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from swag_bot.errors import SwagError

_KIND_ORDER = {"dir": 0, "symlink": 1, "file": 2, "special": 3}


class ObjectStore:
    """SHA-256 blob store. Identical contents share one file."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects"
        self.stat_cache: dict[tuple[str, int, int], str] = {}

    def put(self, data: bytes) -> str:
        """Store ``data`` and return its hex digest."""
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if path.is_file():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return digest

    def get(self, digest: str) -> bytes:
        """Return the blob for ``digest``. Raise ``SwagError`` if it is missing."""
        path = self._path(digest)
        if not path.is_file():
            raise SwagError(f"undo snapshot is missing blob {digest}")
        return path.read_bytes()

    def _path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest[2:]


def capture_tree(root: Path, store: ObjectStore, *, ignore: Path | None = None) -> str:
    """Snapshot ``root`` and return the tree hash.

    Regular files, directories, and symlinks are recorded. Sockets, devices,
    and fifos are noted as ``special`` and left alone on restore. Symlinks are
    not followed, so a link that points outside the workdir does not pull
    that outside file into the snapshot.
    """
    workdir = root.resolve()
    entries = _walk(workdir, store, ignore=ignore)
    payload = json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return store.put(payload)


def restore_tree(
    root: Path,
    store: ObjectStore,
    tree: str,
    *,
    ignore: Path | None = None,
) -> int:
    """Make ``root`` match ``tree``. Return how many paths were created, updated, or removed."""
    workdir = root.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(store, tree)
    desired = {entry["path"]: entry for entry in manifest}
    existing = _existing(workdir, ignore=ignore)
    changed = 0
    extras = [rel for rel in existing if rel not in desired]
    extras.sort(key=lambda rel: rel.count("/"), reverse=True)
    for rel in extras:
        _remove_path(existing[rel])
        changed += 1
    ordered = sorted(manifest, key=_entry_key)
    for entry in ordered:
        if _place(workdir, entry, store):
            changed += 1
    return changed


def _walk(workdir: Path, store: ObjectStore, *, ignore: Path | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not workdir.exists():
        return entries
    for dirpath, dirnames, filenames in os.walk(workdir, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            child = current / name
            if _ignored(child, ignore):
                continue
            if child.is_symlink():
                entries.append(_symlink_entry(workdir, child))
                continue
            kept.append(name)
        dirnames[:] = kept
        if current != workdir and not _ignored(current, ignore):
            entries.append(_dir_entry(workdir, current))
        for name in filenames:
            child = current / name
            if _ignored(child, ignore):
                continue
            entries.append(_file_entry(workdir, child, store))
    entries.sort(key=lambda item: str(item["path"]))
    return entries


def _file_entry(workdir: Path, path: Path, store: ObjectStore) -> dict[str, Any]:
    rel = path.relative_to(workdir).as_posix()
    if path.is_symlink():
        return _symlink_entry(workdir, path)
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISREG(info.st_mode):
        return {"kind": "special", "mode": mode, "path": rel}
    key = (str(path.resolve()), info.st_mtime_ns, info.st_size)
    cached = store.stat_cache.get(key)
    if cached is None:
        try:
            cached = store.put(path.read_bytes())
        except OSError as exc:
            raise SwagError(f"cannot snapshot {rel}: {exc}") from exc
        store.stat_cache[key] = cached
    return {"hash": cached, "kind": "file", "mode": mode, "path": rel}


def _symlink_entry(workdir: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(workdir).as_posix()
    try:
        target = os.readlink(path)
    except OSError as exc:
        raise SwagError(f"cannot snapshot symlink {rel}: {exc}") from exc
    mode = stat.S_IMODE(path.lstat().st_mode)
    return {"kind": "symlink", "mode": mode, "path": rel, "target": target}


def _dir_entry(workdir: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(workdir).as_posix()
    mode = stat.S_IMODE(path.lstat().st_mode)
    return {"kind": "dir", "mode": mode, "path": rel}


def _existing(workdir: Path, *, ignore: Path | None) -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not workdir.exists():
        return found
    for dirpath, dirnames, filenames in os.walk(workdir, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            child = current / name
            if _ignored(child, ignore):
                continue
            if child.is_symlink():
                found[child.relative_to(workdir).as_posix()] = child
                continue
            kept.append(name)
        dirnames[:] = kept
        if current != workdir and not _ignored(current, ignore):
            found[current.relative_to(workdir).as_posix()] = current
        for name in filenames:
            child = current / name
            if _ignored(child, ignore):
                continue
            found[child.relative_to(workdir).as_posix()] = child
    return found


def _place(workdir: Path, entry: dict[str, Any], store: ObjectStore) -> bool:
    rel = str(entry["path"])
    if _unsafe_relative(rel):
        raise SwagError(f"undo snapshot has an unsafe path: {rel}")
    path = workdir / rel
    kind = str(entry["kind"])
    mode = int(entry.get("mode", 0o644))
    if kind == "special":
        return False
    if kind == "dir":
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            _remove_path(path)
        existed = path.is_dir() and not path.is_symlink()
        path.mkdir(parents=True, exist_ok=True)
        _chmod(path, mode)
        return not existed
    if kind == "symlink":
        target = str(entry.get("target", ""))
        if path.is_symlink() and os.readlink(path) == target:
            return False
        if path.is_symlink() or path.exists():
            _remove_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        return True
    if kind == "file":
        data = store.get(str(entry["hash"]))
        if path.is_file() and not path.is_symlink():
            try:
                same = path.read_bytes() == data
            except OSError:
                same = False
            if same:
                _chmod(path, mode)
                return False
        if path.is_symlink() or path.exists():
            _remove_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".swag-undo-tmp")
        temporary.write_bytes(data)
        _chmod(temporary, mode)
        os.replace(temporary, path)
        return True
    raise SwagError(f"undo snapshot has an unknown entry kind: {kind}")


def _load_manifest(store: ObjectStore, tree: str) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(store.get(tree))
    except json.JSONDecodeError as exc:
        raise SwagError(f"undo snapshot {tree} is not a tree") from exc
    if not isinstance(loaded, list):
        raise SwagError(f"undo snapshot {tree} is not a tree")
    entries: list[dict[str, Any]] = []
    for item in loaded:
        if not isinstance(item, dict) or "path" not in item or "kind" not in item:
            raise SwagError(f"undo snapshot {tree} has a broken entry")
        entries.append(item)
    return entries


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink()
        return
    if path.is_dir():
        for child in list(path.iterdir()):
            _remove_path(child)
        path.rmdir()
        return
    path.unlink()


def _chmod(path: Path, mode: int) -> None:
    if path.is_symlink():
        return
    try:
        os.chmod(path, mode)
    except OSError:
        return


def _ignored(path: Path, ignore: Path | None) -> bool:
    if ignore is None:
        return False
    try:
        path.resolve().relative_to(ignore.resolve())
    except ValueError:
        return False
    return True


def _unsafe_relative(rel: str) -> bool:
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        return True
    return any(part == ".." for part in Path(rel).parts)


def _entry_key(entry: dict[str, Any]) -> tuple[int, int, str]:
    path = str(entry["path"])
    kind = str(entry["kind"])
    return (path.count("/"), _KIND_ORDER.get(kind, 9), path)
