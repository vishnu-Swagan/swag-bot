"""Replay a run from a bundle.

``replay_run`` is the API other features should call. Recorded mode never
contacts a model: it returns the saved responses in request order, matched
by a fingerprint of the redacted prompt so parallel steps can be reordered.
Live mode calls the client you pass and reports how the new run differs.
"""

from __future__ import annotations

import inspect
import json
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from swag_bot.core.bundle.files import load_blobs, restore_files, snapshot_workdir
from swag_bot.core.bundle.record import fingerprint, tool_key
from swag_bot.core.bundle.redact import redact_text
from swag_bot.core.bundle.store import LoadedBundle, load_bundle, read_jsonl
from swag_bot.core.fallbacks import FallbackPolicy, LocalSandbox
from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.errors import SwagError
from swag_bot.interfaces import (
    ActionRequest,
    AutonomyLevel,
    ChatResponse,
    LLMClient,
    MemoryItem,
    Message,
    Tool,
)
from swag_bot.registry import InMemoryToolRegistry


class ReplayReport(BaseModel):
    """What ``replay_run`` returns. ``matched`` compares this run to the bundle."""

    model_config = ConfigDict(extra="ignore")

    mode: str
    goal: str
    matched: bool
    differences: list[str] = Field(default_factory=list)
    output_dir: str
    step_status: dict[str, str] = Field(default_factory=dict)
    model_mismatches: int = 0
    bundle: str = ""
    summary: str = ""


@runtime_checkable
class RunReplayer(Protocol):
    """Replay API for skill tests and other callers.

    Recorded mode is offline. Pass ``llm`` only for ``mode="live"``.
    """

    def replay(
        self,
        bundle: str | Path,
        *,
        mode: str = "recorded",
        workdir: str | Path | None = None,
        llm: LLMClient | None = None,
    ) -> ReplayReport:
        """Re-execute ``bundle`` and return the comparison."""
        ...


class BundleReplayer:
    """Default ``RunReplayer``. ``replay_run`` is the same function."""

    def replay(
        self,
        bundle: str | Path,
        *,
        mode: str = "recorded",
        workdir: str | Path | None = None,
        llm: LLMClient | None = None,
    ) -> ReplayReport:
        directory = None if workdir is None else Path(workdir)
        return replay_run(bundle, mode=mode, workdir=directory, llm=llm)


def replay_run(
    bundle: str | Path | LoadedBundle,
    *,
    mode: str = "recorded",
    llm: LLMClient | None = None,
    workdir: Path | None = None,
    tool_mode: str = "rerun",
) -> ReplayReport:
    """Re-execute a bundle.

    ``mode="recorded"`` uses saved model responses and does not call a live
    model. ``mode="live"`` calls ``llm`` and compares the new run to the
    bundle. ``tool_mode="rerun"`` runs the tools again. ``tool_mode="recorded"``
    returns the saved tool results and then restores the saved files.
    """
    if mode not in {"recorded", "live"}:
        raise SwagError("replay mode must be recorded or live")
    if tool_mode not in {"rerun", "recorded"}:
        raise SwagError("replay tools must be rerun or recorded")
    if mode == "live" and llm is None:
        raise SwagError("live replay needs a model client")
    if isinstance(bundle, LoadedBundle):
        loaded = bundle
        owns_bundle = False
    else:
        loaded = load_bundle(Path(bundle))
        owns_bundle = True
    try:
        return _replay(loaded, mode=mode, llm=llm, workdir=workdir, tool_mode=tool_mode)
    finally:
        if owns_bundle:
            loaded.close()


def _replay(
    loaded: LoadedBundle,
    *,
    mode: str,
    llm: LLMClient | None,
    workdir: Path | None,
    tool_mode: str,
) -> ReplayReport:
    manifest = loaded.manifest
    goal = str(manifest.get("goal") or "")
    if not goal.strip():
        raise SwagError("bundle has no goal")
    directory = workdir if workdir is not None else Path.cwd() / "swag-replay"
    if workdir is None:
        from datetime import UTC, datetime

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        directory = Path.cwd() / "swag-replay" / stamp
    directory.mkdir(parents=True, exist_ok=True)
    _restore_tree(loaded.root, directory, which="before")
    if mode == "live":
        if llm is None:
            raise SwagError("live replay needs a model client")
        client: LLMClient = llm
    else:
        client = ReplayLLM(read_jsonl(loaded.root / "model.jsonl"))
    tools = _tools(loaded, directory, tool_mode=tool_mode if mode == "recorded" else "rerun")
    autonomy = _autonomy(manifest.get("autonomy"))
    model_name = _model_name(manifest)
    loop = _make_loop(
        manifest,
        llm=client,
        workdir=directory,
        tools=tools,
        autonomy=autonomy,
        model_name=model_name,
        decisions=_decisions(loaded.root),
        memory=ReplayMemory(read_jsonl(loaded.root / "memory.jsonl")),
    )
    context = manifest.get("planner_context")
    plan = loop.run(
        goal,
        dry_run=bool(manifest.get("dry_run")),
        context=context if isinstance(context, str) else "",
    )
    if mode == "recorded" and tool_mode == "recorded":
        _restore_tree(loaded.root, directory, which="after")
    status = {step.id: step.status.value for step in plan.steps}
    differences = _differences(loaded.root, manifest, directory, status, loop.summary_text)
    mismatch_count = client.mismatches if isinstance(client, ReplayLLM) else 0
    if mismatch_count:
        differences.append(f"{mismatch_count} model requests did not match a recorded prompt")
    return ReplayReport(
        mode=mode,
        goal=goal,
        matched=not differences,
        differences=differences,
        output_dir=str(directory),
        step_status=status,
        model_mismatches=mismatch_count,
        bundle=str(loaded.root),
        summary=loop.summary_text,
    )


class _Slot:
    def __init__(self, kind: str, fingerprint: str, response: ChatResponse) -> None:
        self.kind = kind
        self.fingerprint = fingerprint
        self.response = response
        self.used = False


class ReplayLLM:
    """Offline ``LLMClient``. Responses come from the bundle."""

    def __init__(self, calls: Sequence[Any]) -> None:
        self._slots: list[_Slot] = []
        self.mismatches = 0
        self._lock = threading.Lock()
        for call in calls:
            if not isinstance(call, dict):
                continue
            response = call.get("response")
            if not isinstance(response, dict):
                continue
            self._slots.append(
                _Slot(
                    kind=str(call.get("kind") or "chat"),
                    fingerprint=str(call.get("fingerprint") or ""),
                    response=ChatResponse.model_validate(response),
                )
            )

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        fp = fingerprint(messages, tools, model)
        with self._lock:
            for slot in self._slots:
                if not slot.used and slot.kind == "chat" and slot.fingerprint == fp:
                    slot.used = True
                    return slot.response.model_copy(deep=True)
            for slot in self._slots:
                if not slot.used and slot.kind == "chat":
                    slot.used = True
                    self.mismatches += 1
                    return slot.response.model_copy(deep=True)
        raise SwagError("replay ran out of recorded model responses")

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        response = self.chat([Message.user(prompt)], model=model)
        return response.message.content or ""


class _ReplayPrompter:
    def __init__(self, decisions: list[bool]) -> None:
        self._decisions = decisions

    def prompt(self, action: ActionRequest) -> bool:
        del action
        if not self._decisions:
            return False
        return self._decisions.pop(0)


def _make_loop(
    manifest: dict[str, Any],
    *,
    llm: LLMClient,
    workdir: Path,
    tools: InMemoryToolRegistry | None,
    autonomy: AutonomyLevel,
    model_name: str,
    decisions: list[bool],
    memory: ReplayMemory,
) -> PlanDoVerifyLoop:
    """Build the loop, including flags that may land on it later."""
    kwargs: dict[str, Any] = {
        "llm": llm,
        "sandbox": LocalSandbox(workdir),
        "memory": memory,
        "policy": FallbackPolicy(autonomy),
        "prompter": _ReplayPrompter(decisions),
        "tools": tools,
        "model": model_name or None,
        "max_steps": _positive(manifest.get("max_steps"), 8),
        "max_attempts": _positive(manifest.get("max_attempts"), 2),
        "concurrency": _positive(manifest.get("concurrency"), 1),
        "engine": str(manifest.get("engine") or "python"),
    }
    # strict_plan and memory_mode are recorded for the step-handoff work.
    # Pass them only when this checkout's loop already accepts them.
    kwargs.update(_future_kwargs(manifest))
    return PlanDoVerifyLoop(**kwargs)


def _tools(loaded: LoadedBundle, workdir: Path, *, tool_mode: str) -> InMemoryToolRegistry | None:
    del workdir
    if tool_mode != "recorded":
        return None
    queues: dict[str, list[str]] = {}
    names: list[str] = []
    for row in read_jsonl(loaded.root / "tools.jsonl"):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        if not name:
            continue
        if name not in names:
            names.append(name)
        key = str(row.get("key") or "")
        result = row.get("result")
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        queues.setdefault(key, []).append(text)
    registry = InMemoryToolRegistry()
    for name in _tool_order(loaded.manifest, names):
        handler = _recorded(name, queues)
        registry.register(Tool(name=name, description="Recorded tool result."), handler)
    return registry


def _tool_order(manifest: Mapping[str, Any], recorded_names: Sequence[str]) -> list[str]:
    """Register tools in the order the planner saw them.

    The planner prompt lists tool names in registration order. Built-ins are
    ``read_file``, ``write_file``, ``run_shell``. Replaying only the tools
    that were called would put the first called tool ahead of the others.
    """
    raw = manifest.get("tool_order")
    order: list[str] = []
    if isinstance(raw, list):
        order = [item for item in raw if isinstance(item, str) and item]
    if not order:
        order = ["read_file", "write_file", "run_shell"]
    for name in recorded_names:
        if name not in order:
            order.append(name)
    return order


class ReplayMemory:
    """Memory that returns the search hits stored in ``memory.jsonl``.

    Step searches are keyed by the redacted query. Planner recall is stored
    on the manifest as ``planner_context`` and is not served here. Writes
    during replay are kept for ``get`` and do not change later searches.
    """

    def __init__(self, rows: Sequence[Any]) -> None:
        self._queues: dict[str, list[list[str]]] = {}
        self._items: dict[str, MemoryItem] = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("op") != "search":
                continue
            if row.get("phase") == "planner":
                continue
            query = row.get("query")
            if not isinstance(query, str):
                continue
            results = row.get("results")
            contents = [str(item) for item in results] if isinstance(results, list) else []
            self._queues.setdefault(query, []).append(contents)

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        item = MemoryItem(id=uuid4().hex, content=content, metadata=dict(metadata or {}))
        self._items[item.id] = item
        return item

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        if limit <= 0:
            return []
        bucket = self._queues.get(redact_text(query))
        contents = bucket.pop(0) if bucket else []
        found: list[MemoryItem] = []
        for content in contents[:limit]:
            item = MemoryItem(id=uuid4().hex, content=content)
            self._items[item.id] = item
            found.append(item)
        return found

    def get(self, item_id: str) -> MemoryItem | None:
        return self._items.get(item_id)

    def delete(self, item_id: str) -> bool:
        return self._items.pop(item_id, None) is not None


def _recorded(name: str, queues: dict[str, list[str]]) -> Any:
    def handler(**arguments: Any) -> str:
        key = tool_key(name, arguments)
        bucket = queues.get(key)
        if bucket:
            return bucket.pop(0)
        return "error: no recorded tool result"

    return handler


def _decisions(root: Path) -> list[bool]:
    found: list[bool] = []
    for row in read_jsonl(root / "approvals.jsonl"):
        if isinstance(row, dict) and "approved" in row:
            found.append(bool(row.get("approved")))
    return found


def _restore_tree(bundle_root: Path, workdir: Path, *, which: str) -> None:
    path = bundle_root / "files" / "trees.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    side = data.get(which)
    if not isinstance(side, dict):
        return
    entries = side.get("entries")
    if not isinstance(entries, list):
        return
    typed = [item for item in entries if isinstance(item, dict)]
    restore_files(workdir, typed, load_blobs(bundle_root))


def _differences(
    bundle_root: Path,
    manifest: dict[str, Any],
    workdir: Path,
    status: dict[str, str],
    summary: str,
) -> list[str]:
    differences: list[str] = []
    result = manifest.get("result")
    expected: dict[str, Any] = {}
    if isinstance(result, dict) and isinstance(result.get("step_status"), dict):
        expected = result["step_status"]
    for step_id, recorded in expected.items():
        actual = status.get(str(step_id))
        if actual != recorded:
            differences.append(f"step {step_id} is {actual}, the bundle recorded {recorded}")
    for step_id in status:
        if step_id not in expected:
            differences.append(f"step {step_id} was not in the bundle")
    expected_files = _expected_files(bundle_root)
    current = snapshot_workdir(workdir)
    actual_files = {
        str(entry["path"]): str(entry["hash"])
        for entry in current.entries
        if entry.get("kind") == "file" and isinstance(entry.get("path"), str)
    }
    for path, digest in expected_files.items():
        if actual_files.get(path) != digest:
            differences.append(f"file {path} does not match the bundle")
    for path in actual_files:
        if path not in expected_files:
            differences.append(f"file {path} was not in the recorded workspace")
    recorded_summary = (bundle_root / "summary.md").read_text(encoding="utf-8") if (
        bundle_root / "summary.md"
    ).is_file() else ""
    if redact_text(summary).strip() != recorded_summary.strip():
        differences.append("summary does not match the bundle")
    return differences


def _expected_files(bundle_root: Path) -> dict[str, str]:
    path = bundle_root / "files" / "trees.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    after = data.get("after")
    if not isinstance(after, dict) or not isinstance(after.get("entries"), list):
        return {}
    found: dict[str, str] = {}
    for entry in after["entries"]:
        if not isinstance(entry, dict) or entry.get("kind") != "file":
            continue
        rel = entry.get("path")
        digest = entry.get("hash")
        if isinstance(rel, str) and isinstance(digest, str):
            found[rel] = digest
    return found


def _autonomy(value: Any) -> AutonomyLevel:
    try:
        return AutonomyLevel(str(value))
    except ValueError:
        return AutonomyLevel.ASK_RISKY


def _model_name(manifest: dict[str, Any]) -> str:
    model = manifest.get("model")
    if isinstance(model, dict) and isinstance(model.get("model"), str):
        return str(model["model"])
    return ""


def _positive(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value


def _future_kwargs(manifest: dict[str, Any]) -> dict[str, Any]:
    """Pass flags the loop may grow later (strict plan, memory mode)."""
    params = inspect.signature(PlanDoVerifyLoop.__init__).parameters
    extra: dict[str, Any] = {}
    strict = manifest.get("strict_plan")
    if "strict_plan" in params and isinstance(strict, bool):
        extra["strict_plan"] = strict
    memory_mode = manifest.get("memory_mode")
    if "memory_mode" in params and isinstance(memory_mode, str) and memory_mode:
        extra["memory_mode"] = memory_mode
    return extra
