"""Read and write a run bundle directory or zip archive."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swag_bot.core.bundle.spec import SPEC_ID
from swag_bot.errors import SwagError


@dataclass
class LoadedBundle:
    """A bundle directory. Close it when it was unpacked from a zip."""

    root: Path
    manifest: dict[str, Any]
    _temporary: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def __enter__(self) -> LoadedBundle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def load_bundle(path: Path) -> LoadedBundle:
    """Open a bundle directory or a ``.zip`` archive."""
    if not path.exists():
        raise SwagError(f"bundle not found: {path}")
    if path.is_dir():
        return LoadedBundle(root=path, manifest=_read_manifest(path))
    if zipfile.is_zipfile(path):
        temporary = tempfile.TemporaryDirectory(prefix="swag-bundle-")
        dest = Path(temporary.name)
        try:
            _safe_extract(path, dest)
            manifest = _read_manifest(dest)
        except Exception:
            temporary.cleanup()
            raise
        return LoadedBundle(root=dest, manifest=manifest, _temporary=temporary)
    raise SwagError(f"bundle must be a directory or a zip file: {path}")


def export_bundle(source: Path, destination: Path) -> Path:
    """Zip a bundle directory. ``source`` may already be a zip, which is copied."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file() and zipfile.is_zipfile(source):
        shutil.copyfile(source, destination)
        return destination
    if not source.is_dir():
        raise SwagError(f"bundle not found: {source}")
    if not (source / "manifest.json").is_file():
        raise SwagError(f"{source} is not a run bundle (missing manifest.json)")
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return destination


def describe_bundle(bundle: LoadedBundle) -> str:
    """Plain-language summary of a bundle."""
    manifest = bundle.manifest
    model = manifest.get("model")
    provider = ""
    model_name = ""
    if isinstance(model, dict):
        provider = str(model.get("provider") or "")
        model_name = str(model.get("model") or "")
    result = manifest.get("result")
    statuses: dict[str, Any] = {}
    if isinstance(result, dict) and isinstance(result.get("step_status"), dict):
        statuses = result["step_status"]
    counts = manifest.get("counts")
    model_calls = _count(counts, "model_calls", bundle.root / "model.jsonl")
    tool_calls = _count(counts, "tool_calls", bundle.root / "tools.jsonl")
    approvals = _count(counts, "approvals", bundle.root / "approvals.jsonl")
    evidence = manifest.get("evidence")
    evidence_source = ""
    evidence_spec = ""
    if isinstance(evidence, dict):
        evidence_source = str(evidence.get("source") or "")
        evidence_spec = f"{evidence.get('spec')} {evidence.get('version')}"
    undo = manifest.get("undo")
    undo_present = isinstance(undo, dict) and bool(undo.get("present"))
    changes = _read_json(bundle.root / "files" / "diffs.json")
    changed = 0
    if isinstance(changes, list):
        changed = len(changes)
    step_bits = [f"{step_id} {status}" for step_id, status in statuses.items()]
    lines = [
        f"Run bundle {manifest.get('version')} ({manifest.get('spec')})",
        f"Goal: {manifest.get('goal')}",
        f"Model: {provider} / {model_name}".rstrip(),
        f"Swag: {manifest.get('swag_version')}",
        f"Steps: {', '.join(step_bits) if step_bits else '(none)'}",
        f"Model calls: {model_calls}",
        f"Tool calls: {tool_calls}",
        f"Approvals: {approvals}",
        f"Plan fallback: {'yes' if manifest.get('plan_fallback') else 'no'}",
        f"Strict plan: {_optional(manifest.get('strict_plan'))}",
        f"Memory mode: {_optional(manifest.get('memory_mode'))}",
        f"Files changed: {changed}",
        f"Evidence: {evidence_source or 'missing'} ({evidence_spec})",
        f"Undo snapshots: {'yes' if undo_present else 'no'}",
        "Secrets: redacted" if manifest.get("redacted") else "Secrets: unknown",
    ]
    return "\n".join(lines)


def read_jsonl(path: Path) -> list[Any]:
    """Read a JSONL file. A missing file is an empty list."""
    if not path.is_file():
        return []
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _read_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file():
        raise SwagError(f"{root} is not a run bundle (missing manifest.json)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SwagError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SwagError(f"cannot read {path}: manifest must be an object")
    if data.get("spec") != SPEC_ID:
        raise SwagError(
            f"{path} is not a Swag run bundle (spec is {data.get('spec')!r}, expected {SPEC_ID})"
        )
    version = str(data.get("version") or "")
    if not version.startswith("1."):
        raise SwagError(f"unsupported run bundle version {version!r}")
    return data


def _safe_extract(archive_path: Path, dest: Path) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if not name or name.startswith(("/", "\\")) or Path(name).is_absolute():
                raise SwagError(f"bundle path escapes the archive: {name}")
            if ".." in Path(name).parts:
                raise SwagError(f"bundle path escapes the archive: {name}")
            target = (dest / name).resolve()
            if target != root and root not in target.parents:
                raise SwagError(f"bundle path escapes the archive: {name}")
        archive.extractall(dest)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _count(counts: Any, key: str, path: Path) -> int:
    if isinstance(counts, dict) and isinstance(counts.get(key), int):
        return int(counts[key])
    return len(read_jsonl(path))


def _optional(value: Any) -> str:
    if value is None or value == "":
        return "not recorded"
    return str(value)
