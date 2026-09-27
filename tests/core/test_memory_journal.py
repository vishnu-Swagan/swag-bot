"""Memory writes carry provenance and follow ask, auto, and off."""

from __future__ import annotations

from pathlib import Path

from swag_bot.core.memory_journal import (
    append_remembered,
    commit_memory,
    label_memory,
    provenance_metadata,
    recall_lines,
)
from swag_bot.core.prompts import EXECUTOR_PREFIX
from swag_bot.interfaces import ChatResponse, Message, StepStatus, ToolCall
from tests.core.support import DenyPrompter, make_loop, plan_json, verdict
from tests.fakes import AutoApprovePrompter, FakeLLMClient, InMemoryMemoryStore


def _step(step_id: str, title: str) -> dict[str, object]:
    return {
        "id": step_id,
        "title": title,
        "instruction": title,
        "success_criteria": "the step is done",
    }


def _systems(llm: FakeLLMClient, prefix: str) -> list[list[Message]]:
    return [messages for messages in llm.messages if (messages[0].content or "").startswith(prefix)]


def test_auto_save_records_run_step_and_evidence() -> None:
    store = InMemoryMemoryStore()
    notice = commit_memory(
        store,
        "Write the note: wrote note.txt",
        mode="auto",
        prompter=None,
        metadata=provenance_metadata(
            run_id="run-9",
            kind="step",
            goal="write a note",
            step_id="write",
            evidence_ids=(),
        ),
    )
    assert notice is not None and notice.saved
    assert notice.text.startswith("remembered:")
    assert "run run-9" in notice.text
    assert "step write" in notice.text
    assert "evidence none" in notice.text
    item = store.search("note")[0]
    assert item.metadata["run_id"] == "run-9"
    assert item.metadata["evidence_ids"] == []
    assert "run run-9" in recall_lines([item])[0]


def test_ask_declined_does_not_store() -> None:
    store = InMemoryMemoryStore()
    notice = commit_memory(
        store,
        "a fact",
        mode="ask",
        prompter=DenyPrompter(),
        metadata=provenance_metadata(run_id="r", kind="step", goal="g", step_id="s"),
    )
    assert notice is not None and notice.saved is False
    assert "declined" in notice.text
    assert store.search("fact") == []


def test_ask_approved_stores() -> None:
    store = InMemoryMemoryStore()
    prompter = AutoApprovePrompter()
    notice = commit_memory(
        store,
        "a fact",
        mode="ask",
        prompter=prompter,
        metadata=provenance_metadata(run_id="r", kind="run-summary", goal="g"),
    )
    assert notice is not None and notice.saved
    assert prompter.prompts[0].kind == "memory"
    assert store.search("fact")


def test_off_does_not_write() -> None:
    store = InMemoryMemoryStore()
    assert (
        commit_memory(
            store,
            "a fact",
            mode="auto",
            prompter=None,
            metadata={"kind": "step"},
        )
        is not None
    )
    assert (
        commit_memory(
            store,
            "hidden",
            mode="off",
            prompter=None,
            metadata={"kind": "step"},
        )
        is None
    )
    assert store.search("hidden") == []


def test_run_summary_recall_stays_short() -> None:
    store = InMemoryMemoryStore()
    item = store.add(
        "# Summary\n\nGoal: write a note\n\n## Steps\n\n- write done\n",
        metadata=provenance_metadata(run_id="run-9", kind="run-summary", goal="write a note"),
    )
    line = recall_lines([item])[0]
    assert line.startswith("recalled: run summary for write a note")
    assert "# Summary" not in line
    assert "run run-9" in line
    assert "evidence none" in line
    assert store.search("Steps")[0].content.startswith("# Summary")


def test_old_memory_without_provenance_says_so() -> None:
    store = InMemoryMemoryStore()
    item = store.add("plain fact")
    assert label_memory(item).endswith("(no provenance)")


def test_append_remembered_adds_one_section() -> None:
    text = append_remembered("# Summary\n\nDone.\n", "remembered: the note")
    assert text.count("## Memory") == 1
    again = append_remembered(text, "remembered: the summary")
    assert again.count("## Memory") == 1
    assert "remembered: the summary" in again


def test_passed_step_memory_is_in_the_summary(tmp_path: Path) -> None:
    loop, _llm, sandbox, memory = make_loop(
        tmp_path,
        [
            plan_json([_step("read", "Read the note")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "note.txt"})]
                )
            ),
            "the file says hello",
            verdict(True, "saw hello"),
            "Read the note.",
        ],
        max_attempts=1,
    )
    sandbox.write_file("note.txt", "hello")
    plan = loop.run("read the note")
    assert plan.steps[0].status is StepStatus.DONE
    saved = memory.search("Read the note")
    assert saved
    assert saved[0].metadata["run_id"] == plan.id
    assert saved[0].metadata["step_id"] == "read"
    assert "remembered:" in loop.summary_text
    evidence_id = loop.results["read"].evidence_ids[0]
    assert evidence_id.startswith("ev-")
    assert f"evidence {evidence_id}" in loop.summary_text
    assert saved[0].metadata["evidence_ids"] == [evidence_id]


def test_off_mode_does_not_put_memory_in_the_executor_prompt(tmp_path: Path) -> None:
    loop, llm, _sandbox, memory = make_loop(
        tmp_path,
        [
            plan_json([_step("only", "Do the work")]),
            "done",
            verdict(True, "ok"),
            "Finished.",
        ],
        max_attempts=1,
    )
    loop.memory_mode = "off"
    loop.evidence_enabled = False
    memory.add(
        "secret earlier summary about Do the work",
        metadata={"kind": "run-summary", "goal": "old"},
    )
    plan = loop.run("do the work")
    assert plan.steps[0].status is StepStatus.DONE
    prompt = _systems(llm, EXECUTOR_PREFIX)[0][-1].content or ""
    assert "secret earlier summary" not in prompt
    assert memory.search("Do the work: done") == []
