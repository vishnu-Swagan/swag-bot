"""Dependency manifests reach the next step."""

from __future__ import annotations

from pathlib import Path

from swag_bot.core.handoff import StepManifest, changed_files, render_handoff, snapshot_text_files
from swag_bot.core.prompts import EXECUTOR_PREFIX
from swag_bot.interfaces import ChatResponse, Message, StepStatus, ToolCall
from tests.core.support import make_loop, plan_json, verdict
from tests.fakes import FakeLLMClient


def _step(step_id: str, title: str, *, depends_on: list[str] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": step_id,
        "title": title,
        "instruction": title,
        "success_criteria": "the step is done",
    }
    if depends_on:
        payload["depends_on"] = depends_on
    return payload


def _systems(llm: FakeLLMClient, prefix: str) -> list[list[Message]]:
    return [messages for messages in llm.messages if (messages[0].content or "").startswith(prefix)]


def test_changed_files_cover_writes_and_deletes(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    (root / "keep.txt").write_text("same", encoding="utf-8")
    before = snapshot_text_files(root)
    (root / "keep.txt").write_text("same", encoding="utf-8")
    (root / "note.txt").write_text("from step 1", encoding="utf-8")
    (root / "gone.txt").write_text("bye", encoding="utf-8")
    mid = snapshot_text_files(root)
    (root / "gone.txt").unlink()
    after = snapshot_text_files(root)
    assert changed_files(before, before) == []
    assert ("note.txt", "from step 1") in changed_files(before, mid)
    deleted = dict(changed_files(mid, after))
    assert deleted["gone.txt"] == "(deleted)"


def test_render_handoff_includes_files_and_evidence() -> None:
    text = render_handoff(
        [
            StepManifest(
                step_id="write",
                title="Write the note",
                observation="wrote note.txt",
                files=(("note.txt", "from step 1"),),
                evidence_ids=("ev-1",),
            )
        ]
    )
    assert "write: Write the note" in text
    assert "note.txt: from step 1" in text
    assert "evidence: ev-1" in text
    assert render_handoff(()) == ""


def test_dependent_step_sees_the_file_and_observation(tmp_path: Path) -> None:
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json(
                [
                    _step("write", "Write the note"),
                    _step("use", "Use the note", depends_on=["write"]),
                ]
            ),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "note.txt", "content": "SECRET-FROM-STEP-1"},
                        )
                    ]
                )
            ),
            "wrote note.txt",
            verdict(True, "file written"),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(id="c2", name="read_file", arguments={"path": "note.txt"})
                    ]
                )
            ),
            "used the note",
            verdict(True, "saw the secret"),
            "Both steps finished.",
        ],
        max_attempts=1,
    )
    plan = loop.run("write a note and then use it")
    assert [step.status for step in plan.steps] == [StepStatus.DONE, StepStatus.DONE]
    prompts = _systems(llm, EXECUTOR_PREFIX)
    first = prompts[0][1].content or ""
    second = next(
        messages[1].content or ""
        for messages in prompts
        if "Use the note" in (messages[1].content or "")
    )
    evidence_id = loop.results["write"].evidence_ids[0]
    assert evidence_id.startswith("ev-")
    assert "Use the note" in second
    assert "Results from earlier steps" not in first
    assert "SECRET-FROM-STEP-1" in second
    assert "note.txt" in second
    assert "wrote note.txt" in second
    assert f"evidence: {evidence_id}" in second
