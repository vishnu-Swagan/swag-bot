"""Record one run into an in-memory bundle, then write it to disk.

Wrappers implement the same protocols as the objects they wrap, so the loop
does not grow a recording mode of its own.
"""

from __future__ import annotations

import json
import platform
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swag_bot import __version__
from swag_bot.core.bundle.context import current_attempt, current_step_id
from swag_bot.core.bundle.evidence_io import copy_redacted_ledger, include_evidence
from swag_bot.core.bundle.files import diff_snapshots, sha256_text, snapshot_workdir, trees_document
from swag_bot.core.bundle.redact import redact_text, redact_value
from swag_bot.core.bundle.spec import SPEC_ID, SPEC_VERSION
from swag_bot.core.bundle.undo_io import undo_view
from swag_bot.interfaces import (
    ActionLogEntry,
    ActionRequest,
    ApprovalPrompter,
    ChatResponse,
    LLMClient,
    MemoryItem,
    MemoryStore,
    Message,
    StepResult,
    TaskPlan,
    Tool,
    ToolCall,
    ToolRegistry,
)


def fingerprint(
    messages: Sequence[Message],
    tools: Sequence[Tool] | None,
    model: str | None,
) -> str:
    """Stable id for one model request, after redaction."""
    payload = {
        "model": model or "",
        "tools": sorted(tool.name for tool in tools) if tools else [],
        "messages": [message_view(message) for message in messages],
    }
    redacted = redact_value(payload)
    blob = json.dumps(redacted, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(blob)


def tool_key(name: str, arguments: Mapping[str, Any]) -> str:
    """Stable id for one tool call, after redaction."""
    payload = redact_value({"arguments": dict(arguments), "name": name})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def message_view(message: Message) -> dict[str, Any]:
    """JSON-ready view of one chat message."""
    return {
        "role": message.role.value,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ],
    }


class RunRecorder:
    """Collect model calls, tools, approvals, and file diffs for one run."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_base: str | None,
        autonomy: str,
        sandbox_mode: str,
        memory_backend: str,
        max_steps: int,
        max_attempts: int,
        concurrency: int,
        engine: str,
        dry_run: bool,
        home: Path | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_base = api_base
        self.autonomy = autonomy
        self.sandbox_mode = sandbox_mode
        self.memory_backend = memory_backend
        self.max_steps = max_steps
        self.max_attempts = max_attempts
        self.concurrency = concurrency
        self.engine = engine
        self.dry_run = dry_run
        self.home = home
        self.sealed = False
        self.destination: Path | None = None
        self._lock = threading.Lock()
        self._calls: list[dict[str, Any]] = []
        self._tools: list[dict[str, Any]] = []
        self._approvals: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._memory: list[dict[str, Any]] = []
        self._observations: dict[str, str] = {}
        self._step_files: dict[str, list[dict[str, Any]]] = {}
        self._before = snapshot_workdir(Path("."))
        self._workdir: Path | None = None
        self._last_files: dict[str, str] = {}
        self._plan_fallback = False
        self._run_id = ""
        self._goal = ""
        self._evidence_source = "synthesized"
        self.planner_context = ""
        self.tool_names: list[str] = []

    def wrap_llm(self, llm: LLMClient) -> RecordingLLM:
        return RecordingLLM(llm, self)

    def wrap_prompter(self, prompter: ApprovalPrompter) -> RecordingPrompter:
        return RecordingPrompter(prompter, self)

    def wrap_tools(self, tools: ToolRegistry) -> RecordingToolRegistry:
        return RecordingToolRegistry(tools, self)

    def wrap_memory(self, memory: MemoryStore) -> RecordingMemory:
        return RecordingMemory(memory, self)

    def note_files_before(self, workdir: Path) -> None:
        """Snapshot the workspace before any step runs."""
        self._workdir = workdir
        self._before = snapshot_workdir(workdir)
        self._last_files = {
            str(entry["path"]): str(entry["hash"])
            for entry in self._before.entries
            if entry.get("kind") == "file" and isinstance(entry.get("path"), str)
        }

    def observe(
        self,
        kind: str,
        plan: TaskPlan,
        step_id: str | None,
        status: str | None,
        text: str,
    ) -> None:
        """Record one loop event and any file handoff it closes."""
        redacted = redact_text(text)
        with self._lock:
            self._events.append(
                {
                    "kind": kind,
                    "step_id": step_id,
                    "status": status,
                    "text": redacted,
                }
            )
            if kind == "plan":
                self._run_id = plan.id
                self._goal = redact_text(plan.goal)
            if kind == "plan_fallback":
                self._plan_fallback = True
            if kind == "output" and step_id:
                self._observations[step_id] = redacted
            if kind == "memory" and redacted:
                self._events[-1]["text"] = redacted
        if kind == "status" and step_id and status in {"done", "failed", "skipped", "unverified"}:
            self._capture_step_files(step_id)

    def note_chat(
        self,
        *,
        kind: str,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None,
        model: str | None,
        response: ChatResponse,
    ) -> None:
        view = [message_view(message) for message in messages]
        stored_response = redact_value(response.model_dump(mode="json"))
        record = {
            "index": 0,
            "kind": kind,
            "model": model or "",
            "tools": sorted(tool.name for tool in tools) if tools else [],
            "fingerprint": fingerprint(messages, tools, model),
            "messages": redact_value(view),
            "response": stored_response,
        }
        with self._lock:
            record["index"] = len(self._calls)
            self._calls.append(record)

    def note_tool(self, call: ToolCall, result: str) -> None:
        arguments = redact_value(dict(call.arguments))
        if not isinstance(arguments, dict):
            arguments = {}
        record = {
            "name": call.name,
            "call_id": call.id,
            "arguments": arguments,
            "result": redact_text(result),
            "key": tool_key(call.name, arguments),
            "step_id": current_step_id.get(),
            "attempt": current_attempt.get(),
        }
        with self._lock:
            self._tools.append(record)

    def note_approval(self, action: ActionRequest, approved: bool) -> None:
        record = {
            "record": "prompt",
            "approved": approved,
            "action": redact_value(action.model_dump(mode="json")),
        }
        with self._lock:
            self._approvals.append(record)

    def note_memory(self, content: str, metadata: Mapping[str, Any] | None) -> None:
        meta = redact_value(dict(metadata or {}))
        if not isinstance(meta, dict):
            meta = {}
        with self._lock:
            if self._run_id and "run_id" not in meta:
                meta["run_id"] = self._run_id
            self._memory.append(
                {"op": "add", "content": redact_text(content), "metadata": meta}
            )

    def note_search(self, query: str, hits: Sequence[Any]) -> None:
        """Remember what a memory search returned so replay can show the same lines."""
        results: list[Any] = []
        for item in hits:
            if isinstance(item, str):
                results.append({"content": redact_text(item), "metadata": {}})
                continue
            content = str(getattr(item, "content", ""))
            raw_meta = getattr(item, "metadata", {}) or {}
            meta = redact_value(dict(raw_meta)) if isinstance(raw_meta, Mapping) else {}
            if not isinstance(meta, dict):
                meta = {}
            results.append({"content": redact_text(content), "metadata": meta})
        record = {
            "op": "search",
            "phase": "step",
            "query": redact_text(query),
            "results": results,
        }
        with self._lock:
            self._memory.append(record)

    def seal_planner_searches(self) -> None:
        """Mark searches that already happened as planner recall, not step recall.

        The composition root searches memory while building planner context,
        before the loop starts. Replay feeds that text back as
        ``planner_context`` and must not reuse those rows for a later step.
        """
        with self._lock:
            for row in self._memory:
                if row.get("op") == "search":
                    row["phase"] = "planner"

    def finish(
        self,
        directory: Path,
        *,
        plan: TaskPlan | None,
        results: dict[str, StepResult],
        action_log: Sequence[ActionLogEntry],
        summary: str,
        exit_code: int,
        output_dir: Path,
        workdir: Path,
        strict_plan: bool | None,
        memory_mode: str | None,
    ) -> Path:
        """Write the bundle directory. Secrets in the recorded data are already redacted."""
        directory.mkdir(parents=True, exist_ok=True)
        after = snapshot_workdir(workdir)
        changes = diff_snapshots(self._before, after)
        self._write_blobs(directory, self._before.blobs, after.blobs)
        (directory / "files").mkdir(parents=True, exist_ok=True)
        _write_json(directory / "files" / "trees.json", trees_document(self._before, after))
        _write_json(directory / "files" / "diffs.json", changes)
        run_id = plan.id if plan is not None else self._run_id
        goal = redact_text(plan.goal) if plan is not None else self._goal
        actions = [redact_value(entry.model_dump(mode="json")) for entry in action_log]
        if not isinstance(actions, list):
            actions = []
        action_dicts = [item for item in actions if isinstance(item, dict)]
        self._evidence_source = include_evidence(
            directory,
            output_dir,
            run_id=run_id,
            goal=goal,
            tools=list(self._tools),
            actions=action_dicts,
        )
        if plan is not None:
            plan_payload = redact_value(plan.model_dump(mode="json"))
            _write_json(directory / "plan.json", plan_payload)
        else:
            _write_json(directory / "plan.json", {"goal": goal, "steps": []})
        _write_jsonl(directory / "model.jsonl", self._calls)
        _write_jsonl(directory / "tools.jsonl", self._tools)
        _write_jsonl(directory / "approvals.jsonl", self._approvals)
        _write_jsonl(directory / "events.jsonl", self._events)
        _write_jsonl(directory / "memory.jsonl", self._memory)
        _write_jsonl(directory / "handoff.jsonl", self._handoffs(plan, results))
        _write_jsonl(directory / "actions.jsonl", action_dicts)
        summary_text = redact_text(summary)
        if summary_text and not summary_text.endswith("\n"):
            summary_text += "\n"
        (directory / "summary.md").write_text(summary_text, encoding="utf-8")
        undo = undo_view(run_id, workdir, home=self.home)
        manifest = self._manifest(
            plan=plan,
            results=results,
            summary=summary_text,
            exit_code=exit_code,
            strict_plan=strict_plan,
            memory_mode=memory_mode,
            undo=undo,
            goal=goal,
            run_id=run_id,
        )
        _write_json(directory / "manifest.json", manifest)
        self.destination = directory
        self.sealed = True
        return directory

    def attach_external_evidence(self, output_dir: Path) -> None:
        """Copy ``run.jsonl`` if a ledger wrote it after the bundle was sealed."""
        if self.destination is None:
            return
        source = output_dir / "run.jsonl"
        if not source.is_file():
            return
        target = self.destination / "evidence" / "run.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_redacted_ledger(source, target)
        self._evidence_source = "run.jsonl"
        manifest_path = self.destination / "manifest.json"
        if not manifest_path.is_file():
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(manifest, dict):
            evidence = manifest.get("evidence")
            if isinstance(evidence, dict):
                evidence["source"] = "run.jsonl"
            _write_json(manifest_path, manifest)

    def _capture_step_files(self, step_id: str) -> None:
        if self._workdir is None:
            return
        current = snapshot_workdir(self._workdir)
        current_files = {
            str(entry["path"]): str(entry["hash"])
            for entry in current.entries
            if entry.get("kind") == "file" and isinstance(entry.get("path"), str)
        }
        notes: list[dict[str, Any]] = []
        for path in sorted(set(self._last_files) | set(current_files)):
            previous = self._last_files.get(path)
            now = current_files.get(path)
            if previous == now:
                continue
            if now is None:
                op = "delete"
            elif previous is None:
                op = "add"
            else:
                op = "modify"
            notes.append({"path": path, "op": op, "after_sha256": now})
        self._last_files = current_files
        self._step_files[step_id] = notes

    def _handoffs(
        self,
        plan: TaskPlan | None,
        results: dict[str, StepResult],
    ) -> list[dict[str, Any]]:
        if plan is None:
            return []
        rows: list[dict[str, Any]] = []
        for step in plan.steps:
            result = results.get(step.id)
            evidence_ids = list(getattr(result, "evidence_ids", []) or [])
            checks = getattr(step, "checks", None)
            check_payload: list[Any] = []
            if checks:
                for check in checks:
                    dump = getattr(check, "model_dump", None)
                    if callable(dump):
                        check_payload.append(redact_value(dump(mode="json")))
            observation = self._observations.get(step.id, "")
            if result is not None and not observation:
                observation = redact_text(result.observation)
            rows.append(
                {
                    "step_id": step.id,
                    "title": step.title,
                    "status": step.status.value,
                    "depends_on": list(step.depends_on),
                    "observation": observation,
                    "files": self._step_files.get(step.id, []),
                    "evidence_ids": [str(item) for item in evidence_ids],
                    "checks": check_payload,
                }
            )
        return rows

    def _manifest(
        self,
        *,
        plan: TaskPlan | None,
        results: dict[str, StepResult],
        summary: str,
        exit_code: int,
        strict_plan: bool | None,
        memory_mode: str | None,
        undo: dict[str, Any],
        goal: str,
        run_id: str,
    ) -> dict[str, Any]:
        statuses: dict[str, str] = {}
        if plan is not None:
            for step in plan.steps:
                statuses[step.id] = step.status.value
        return {
            "spec": SPEC_ID,
            "version": SPEC_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "swag_version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "run_id": run_id,
            "goal": goal,
            "model": {
                "provider": self.provider,
                "model": self.model,
                "api_base": redact_text(self.api_base or ""),
            },
            "autonomy": self.autonomy,
            "sandbox_mode": self.sandbox_mode,
            "memory_backend": self.memory_backend,
            "max_steps": self.max_steps,
            "max_attempts": self.max_attempts,
            "concurrency": self.concurrency,
            "engine": self.engine,
            "dry_run": self.dry_run,
            "strict_plan": strict_plan,
            "memory_mode": memory_mode,
            "plan_fallback": self._plan_fallback,
            "redacted": True,
            "evidence": {
                "spec": "swag-evidence-contract",
                "version": "1.0",
                "source": self._evidence_source,
                "path": "evidence/run.jsonl",
            },
            "undo": undo,
            "result": {
                "exit_code": exit_code,
                "step_status": statuses,
                "summary_sha256": sha256_text(summary),
            },
            "planner_context": redact_text(self.planner_context),
            "tool_order": list(self.tool_names),
            "counts": {
                "model_calls": len(self._calls),
                "tool_calls": len(self._tools),
                "approvals": len(self._approvals),
                "memory_writes": sum(1 for row in self._memory if row.get("op") != "search"),
            },
        }

    def _write_blobs(self, directory: Path, *groups: dict[str, str]) -> None:
        objects = directory / "files" / "objects"
        seen: set[str] = set()
        for group in groups:
            for digest, text in group.items():
                if digest in seen:
                    continue
                seen.add(digest)
                target = objects / digest[:2] / digest[2:]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")


class RecordingLLM:
    """``LLMClient`` that records every chat and completion."""

    def __init__(self, inner: LLMClient, recorder: RunRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        response = self._inner.chat(messages, tools=tools, model=model)
        self._recorder.note_chat(
            kind="chat",
            messages=messages,
            tools=tools,
            model=model,
            response=response,
        )
        return response

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        text = self._inner.complete(prompt, model=model)
        response = ChatResponse(message=Message.assistant(text), model=model)
        self._recorder.note_chat(
            kind="complete",
            messages=[Message.user(prompt)],
            tools=None,
            model=model,
            response=response,
        )
        return text


class RecordingPrompter:
    """``ApprovalPrompter`` that records the decision."""

    def __init__(self, inner: ApprovalPrompter, recorder: RunRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def prompt(self, action: ActionRequest) -> bool:
        approved = bool(self._inner.prompt(action))
        self._recorder.note_approval(action, approved)
        return approved


class RecordingToolRegistry:
    """``ToolRegistry`` that records each call's real result."""

    def __init__(self, inner: ToolRegistry, recorder: RunRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def register(self, tool: Tool, handler: Callable[..., Any]) -> None:
        self._inner.register(tool, handler)

    def get(self, name: str) -> Tool:
        return self._inner.get(name)

    def list_tools(self) -> Sequence[Tool]:
        return self._inner.list_tools()

    def call(self, tool_call: ToolCall) -> str:
        try:
            result = self._inner.call(tool_call)
        except Exception as exc:
            self._recorder.note_tool(tool_call, f"error: {exc}")
            raise
        self._recorder.note_tool(tool_call, result)
        return result


class RecordingMemory:
    """``MemoryStore`` that records writes and still stores them."""

    def __init__(self, inner: MemoryStore, recorder: RunRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        item = self._inner.add(content, metadata=metadata)
        self._recorder.note_memory(content, metadata)
        return item

    def search(self, query: str, *, limit: int = 5) -> Sequence[MemoryItem]:
        found = list(self._inner.search(query, limit=limit))
        self._recorder.note_search(query, found)
        return found

    def get(self, item_id: str) -> MemoryItem | None:
        return self._inner.get(item_id)

    def delete(self, item_id: str) -> bool:
        return self._inner.delete(item_id)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    path.write_text(text, encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Any]) -> None:
    lines = [json.dumps(row, sort_keys=True, default=str) for row in rows]
    text = "".join(line + "\n" for line in lines)
    path.write_text(text, encoding="utf-8")
