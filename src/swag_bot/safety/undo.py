"""Undo ledger: snapshot the workspace before a write or a shell command.

``swag undo`` restores that snapshot, including files a shell command
edited or deleted. Side effects outside the workdir are not in the
snapshot. Tools register an inverse for those, or the result lists them
as irreversible.

Snapshots live under ``$SWAG_HOME/undo``, not in the workdir.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from swag_bot.config import swag_home
from swag_bot.errors import SwagError
from swag_bot.interfaces import (
    ActionRequest,
    CommandResult,
    Reversibility,
    Sandbox,
    UndoResult,
)
from swag_bot.safety.compensation import (
    CompensationCall,
    CompensationRegistry,
    CompensationSpec,
    resolve_arguments,
)
from swag_bot.safety.reversibility import classify_reversibility
from swag_bot.safety.snapshot import ObjectStore, capture_tree, restore_tree

_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class Checkpoint(BaseModel):
    """One tree captured before a mutation, or at a run or step boundary."""

    reason: str
    step_id: str | None = None
    target: str = ""
    tree: str


class _StoredAction(BaseModel):
    step_id: str
    kind: str
    summary: str
    target: str | None = None
    tool_name: str | None = None
    reversibility: Reversibility
    arguments: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    inverse: str | None = None
    argument_map: dict[str, str] = Field(default_factory=dict)
    entrypoint: str | None = None
    compensated: bool = False


class _StoredRun(BaseModel):
    run_id: str
    workdir: str
    created_at: str
    base_tree: str
    steps: dict[str, str] = Field(default_factory=dict)
    step_order: list[str] = Field(default_factory=list)
    actions: list[_StoredAction] = Field(default_factory=list)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    current_step: str | None = None


class UndoLedger:
    """Snapshots and action records for one workspace.

    ``begin_run`` and ``begin_step`` mark restore points. ``UndoSandbox``
    snapshots and then performs the write or shell command while holding the
    ledger lock, so another step cannot land between the snapshot and the
    change.
    """

    def __init__(
        self,
        store: ObjectStore,
        *,
        runs_dir: Path,
        index_path: Path,
        compensations: CompensationRegistry | None = None,
        auto_rollback: bool = True,
    ) -> None:
        self.store = store
        self.runs_dir = runs_dir
        self.index_path = index_path
        self.compensations = compensations if compensations is not None else CompensationRegistry()
        self._auto_rollback = auto_rollback
        self._lock = threading.RLock()
        self._run: _StoredRun | None = None
        self._workdir: Path | None = None

    @property
    def auto_rollback(self) -> bool:
        return self._auto_rollback

    @property
    def run_id(self) -> str | None:
        return None if self._run is None else self._run.run_id

    @property
    def checkpoints(self) -> list[Checkpoint]:
        if self._run is None:
            return []
        return list(self._run.checkpoints)

    @classmethod
    def open(
        cls,
        workdir: Path,
        *,
        compensations: CompensationRegistry | None = None,
        auto_rollback: bool = True,
        home: Path | None = None,
    ) -> UndoLedger:
        """Open the ledger that will snapshot ``workdir``. Nothing is captured yet."""
        root = _undo_root(home)
        ledger = cls(
            ObjectStore(root),
            runs_dir=root / "runs",
            index_path=root / "index.json",
            compensations=compensations,
            auto_rollback=auto_rollback,
        )
        ledger._workdir = Path(workdir)
        return ledger

    @classmethod
    def load(cls, run_id: str | None = None, *, home: Path | None = None) -> UndoLedger:
        """Load a saved run. The default is the most recent one."""
        root = _undo_root(home)
        ledger = cls(ObjectStore(root), runs_dir=root / "runs", index_path=root / "index.json")
        chosen = run_id or _latest_run_id(ledger.index_path, ledger.runs_dir)
        if chosen is None:
            raise SwagError("no undo history yet. Run a task with undo enabled first.")
        path = ledger.runs_dir / f"{_safe_id(chosen)}.json"
        if not path.is_file():
            raise SwagError(f"no undo history for run {chosen}")
        try:
            ledger._run = _StoredRun.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SwagError(f"cannot read undo history {path}: {exc}") from exc
        ledger._workdir = Path(ledger._run.workdir)
        return ledger

    def begin_run(self, run_id: str, workdir: Path) -> None:
        """Snapshot ``workdir`` as the restore point for the whole run."""
        with self._lock:
            if self._run is not None and self._run.run_id == run_id:
                self._workdir = Path(workdir)
                return
            root = Path(workdir)
            root.mkdir(parents=True, exist_ok=True)
            tree = capture_tree(root, self.store, ignore=self.store.root)
            now = datetime.now(UTC).isoformat()
            self._workdir = root
            self._run = _StoredRun(
                run_id=run_id,
                workdir=str(root.resolve()),
                created_at=now,
                base_tree=tree,
                checkpoints=[
                    Checkpoint(reason="run-start", step_id=None, target=str(root), tree=tree)
                ],
            )
            self._save()

    def begin_step(self, step_id: str) -> None:
        """Snapshot the workspace the first time ``step_id`` starts."""
        with self._lock:
            run = self._require_run()
            if step_id not in run.steps:
                tree = self._capture("step-start", step_id, step_id)
                run.steps[step_id] = tree
                run.step_order.append(step_id)
            run.current_step = step_id
            self._save()

    def snapshot_before_write(self, workdir: Path, path: str) -> None:
        """Snapshot ``workdir`` before a file write. The path is recorded for the log."""
        with self._lock:
            self._ensure_run(workdir)
            self._capture("before-write", path, None)
            self._save()

    def snapshot_before_shell(self, workdir: Path, command: str) -> None:
        """Snapshot ``workdir`` before a shell command, whatever files it may touch."""
        with self._lock:
            self._ensure_run(workdir)
            self._capture("before-shell", command, None)
            self._save()

    def note_action(self, action: ActionRequest, *, outcome: str | None = None) -> None:
        """Record ``action`` for compensation and for the irreversible list."""
        with self._lock:
            run = self._require_run()
            tool = action.tool_name or action.kind
            spec = self.compensations.lookup(tool)
            reversibility = action.reversibility or classify_reversibility(
                action,
                compensations=self.compensations,
                workdir=self._workdir,
            )
            run.actions.append(
                _StoredAction(
                    step_id=run.current_step or "_unscoped",
                    kind=action.kind,
                    summary=action.summary,
                    target=action.target,
                    tool_name=action.tool_name,
                    reversibility=reversibility,
                    arguments=dict(action.arguments),
                    outcome=outcome,
                    inverse=None if spec is None else spec.inverse,
                    argument_map={} if spec is None else dict(spec.argument_map),
                    entrypoint=None if spec is None else spec.entrypoint,
                )
            )
            self._save()

    def rollback_step(self, step_id: str) -> UndoResult:
        """Restore the start of ``step_id`` and compensate that step and later ones."""
        return self.rollback_run(to_step=step_id)

    def rollback_run(self, *, to_step: str | None = None) -> UndoResult:
        """Restore the run start, or the workspace as ``to_step`` began.

        Passing ``to_step`` undoes that step and every step that started
        after it. Irreversible actions in that range are listed, not undone.
        Compensable actions run their inverse in reverse order.
        """
        with self._lock:
            run = self._require_run()
            workdir = self._require_workdir()
            if to_step is None:
                tree = run.base_tree
                label = "run-start"
                selected = list(run.actions)
            else:
                if to_step not in run.steps:
                    raise SwagError(f"no snapshot for step {to_step}")
                tree = run.steps[to_step]
                label = to_step
                selected = [item for item in run.actions if self._in_undone_range(item, to_step)]
            changed = restore_tree(workdir, self.store, tree, ignore=self.store.root)
            self.store.stat_cache.clear()
            ran, skipped, irreversible = self._compensate(selected)
            self._save()
            return UndoResult(
                run_id=run.run_id,
                workdir=str(workdir),
                restored_to=label,
                files_changed=changed,
                compensations_ran=ran,
                compensations_skipped=skipped,
                irreversible=irreversible,
            )

    def _ensure_run(self, workdir: Path) -> None:
        if self._run is None:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            # begin_run takes the same re-entrant lock.
            self.begin_run(f"adhoc-{stamp}", workdir)
            return
        self._workdir = Path(workdir)

    def _capture(self, reason: str, target: str, step_id: str | None) -> str:
        workdir = self._require_workdir()
        tree = capture_tree(workdir, self.store, ignore=self.store.root)
        run = self._require_run()
        recorded_step = step_id if step_id is not None else run.current_step
        run.checkpoints.append(
            Checkpoint(reason=reason, step_id=recorded_step, target=target, tree=tree)
        )
        return tree

    def _compensate(
        self, actions: list[_StoredAction]
    ) -> tuple[list[str], list[str], list[str]]:
        ran: list[str] = []
        skipped: list[str] = []
        irreversible: list[str] = []
        for action in reversed(actions):
            if action.compensated:
                continue
            if action.reversibility is Reversibility.IRREVERSIBLE:
                irreversible.append(action.summary)
                continue
            if action.reversibility is not Reversibility.COMPENSABLE:
                continue
            self._ensure_spec(action)
            call = CompensationCall(
                tool=action.tool_name or action.kind,
                inverse=action.inverse or action.kind,
                arguments=dict(action.arguments),
                outcome=action.outcome,
                argument_map=dict(action.argument_map),
                resolved=resolve_arguments(action.argument_map, action.arguments, action.outcome),
            )
            ok, message = self.compensations.run(call)
            label = action.inverse or action.summary
            if ok:
                action.compensated = True
                ran.append(f"{label}: {message}" if message else label)
            else:
                skipped.append(f"{action.summary}: {message}")
        return ran, skipped, irreversible

    def _ensure_spec(self, action: _StoredAction) -> None:
        tool = action.tool_name or action.kind
        if self.compensations.lookup(tool) is not None or not action.inverse:
            return
        self.compensations.register(
            CompensationSpec(
                tool=tool,
                inverse=action.inverse,
                argument_map=dict(action.argument_map),
                entrypoint=action.entrypoint,
            )
        )

    def _in_undone_range(self, action: _StoredAction, to_step: str) -> bool:
        run = self._require_run()
        if to_step not in run.step_order:
            return action.step_id == to_step
        start = run.step_order.index(to_step)
        undone = set(run.step_order[start:])
        return action.step_id in undone

    def _require_run(self) -> _StoredRun:
        if self._run is None:
            raise SwagError("undo has no run to restore")
        return self._run

    def _require_workdir(self) -> Path:
        if self._workdir is None:
            if self._run is not None:
                self._workdir = Path(self._run.workdir)
            else:
                raise SwagError("undo has no workspace to snapshot")
        return self._workdir

    def _save(self) -> None:
        run = self._require_run()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{_safe_id(run.run_id)}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)
        _write_index(self.index_path, run)


class UndoSandbox:
    """Sandbox wrapper that snapshots before every write and shell command.

    ``undo_wrapped`` tells the composition root not to wrap a second time.
    Reads are not snapshotted.
    """

    undo_wrapped = True

    def __init__(self, inner: Sandbox, ledger: UndoLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    @property
    def workdir(self) -> Path:
        return self._inner.workdir

    def read_file(self, path: str) -> str:
        return self._inner.read_file(path)

    def write_file(self, path: str, content: str) -> None:
        with self._ledger._lock:
            self._ledger.snapshot_before_write(self.workdir, path)
            self._inner.write_file(path, content)

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        with self._ledger._lock:
            self._ledger.snapshot_before_shell(self.workdir, command)
            return self._inner.run(command, timeout=timeout)


def describe_undo(result: UndoResult) -> str:
    """Plain-language report of an undo, including what was not undone."""
    if result.restored_to == "run-start":
        where = "the start of the run"
    else:
        where = f"the start of step {result.restored_to}"
    lines = [
        f"Run {result.run_id}: restored {result.workdir} to {where} "
        f"({result.files_changed} paths changed)."
    ]
    if result.compensations_ran:
        lines.append("Ran compensating actions:")
        lines.extend(f"- {item}" for item in result.compensations_ran)
    if result.compensations_skipped:
        lines.append("Compensating actions that did not run:")
        lines.extend(f"- {item}" for item in result.compensations_skipped)
    if result.irreversible:
        lines.append("Irreversible actions were not undone:")
        lines.extend(f"- {item}" for item in result.irreversible)
    else:
        lines.append("No irreversible actions were recorded in the undone range.")
    return "\n".join(lines)


def _undo_root(home: Path | None) -> Path:
    base = swag_home() if home is None else home
    return base / "undo"


def _safe_id(value: str) -> str:
    cleaned = _SAFE_ID.sub("_", value).strip("._")
    if not cleaned:
        raise SwagError("run id is empty")
    return cleaned[:200]


def _latest_run_id(index_path: Path, runs_dir: Path) -> str | None:
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SwagError(f"cannot read {index_path}: {exc}") from exc
        runs = data.get("runs") if isinstance(data, dict) else None
        if isinstance(runs, list) and runs:
            last = runs[-1]
            if isinstance(last, dict) and isinstance(last.get("id"), str):
                return str(last["id"])
    if not runs_dir.is_dir():
        return None
    files = sorted(runs_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
    if not files:
        return None
    return files[-1].stem


def _write_index(path: Path, run: _StoredRun) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, str]] = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        raw = loaded.get("runs") if isinstance(loaded, dict) else None
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("id") != run.run_id:
                    ident = item.get("id")
                    if isinstance(ident, str):
                        runs.append(
                            {
                                "id": ident,
                                "workdir": str(item.get("workdir", "")),
                                "created_at": str(item.get("created_at", "")),
                            }
                        )
    runs.append({"id": run.run_id, "workdir": run.workdir, "created_at": run.created_at})
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"runs": runs}, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
