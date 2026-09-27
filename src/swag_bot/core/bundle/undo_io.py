"""Read undo-ledger checkpoints when that feature has saved them.

The undo ledger (draft, ``$SWAG_HOME/undo``) stores content-addressed trees.
This module does not import it. It reads the JSON the ledger writes, when
the file is there, and copies tree hashes into the bundle. The blobs stay
in the undo store; the bundle carries its own redacted file bytes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from swag_bot.config import swag_home
from swag_bot.core.bundle.spec import UNDO_ALIGNMENT

_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def undo_view(run_id: str, workdir: Path | None, *, home: Path | None = None) -> dict[str, Any]:
    """Tree hashes for this run, or an empty view when undo has nothing saved."""
    empty: dict[str, Any] = {
        "aligned_with": UNDO_ALIGNMENT,
        "present": False,
        "store": "$SWAG_HOME/undo",
        "run_id": None,
        "base_tree": None,
        "checkpoints": [],
    }
    root = (swag_home() if home is None else home) / "undo"
    runs = root / "runs"
    if not runs.is_dir():
        return empty
    chosen = _by_id(runs, run_id)
    if chosen is None and workdir is not None:
        chosen = _by_workdir(root, workdir)
    if chosen is None:
        return empty
    try:
        data = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    checkpoints = _checkpoints(data.get("checkpoints"))
    base = data.get("base_tree")
    return {
        "aligned_with": UNDO_ALIGNMENT,
        "present": True,
        "store": "$SWAG_HOME/undo",
        "run_id": data.get("run_id") if isinstance(data.get("run_id"), str) else None,
        "base_tree": base if isinstance(base, str) else None,
        "checkpoints": checkpoints,
    }


def _by_id(runs: Path, run_id: str) -> Path | None:
    if not run_id:
        return None
    cleaned = _SAFE_ID.sub("_", run_id).strip("._")[:200]
    if not cleaned:
        return None
    path = runs / f"{cleaned}.json"
    return path if path.is_file() else None


def _by_workdir(root: Path, workdir: Path) -> Path | None:
    wanted = str(workdir.resolve())
    index = root / "index.json"
    run_ids: list[str] = []
    if index.is_file():
        try:
            loaded = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        raw = loaded.get("runs") if isinstance(loaded, dict) else None
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                ident = item.get("id")
                recorded = item.get("workdir")
                if isinstance(ident, str) and isinstance(recorded, str) and _same(recorded, wanted):
                    run_ids.append(ident)
    runs = root / "runs"
    for ident in reversed(run_ids):
        found = _by_id(runs, ident)
        if found is not None:
            return found
    return None


def _same(recorded: str, wanted: str) -> bool:
    try:
        return str(Path(recorded).resolve()) == wanted
    except OSError:
        return recorded == wanted


def _checkpoints(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tree = item.get("tree")
        if not isinstance(tree, str):
            continue
        step_id = item.get("step_id")
        rows.append(
            {
                "reason": str(item.get("reason") or ""),
                "step_id": step_id if isinstance(step_id, str) else None,
                "tree": tree,
            }
        )
    return rows
