"""Plan-do-verify loop with the scripted FakeLLMClient."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.core.prompts import (
    EXECUTOR_PREFIX,
    PLANNER_PREFIX,
    SUMMARIZER_PREFIX,
    VERIFIER_PREFIX,
)
from swag_bot.interfaces import (
    ActionKind,
    ActionRequest,
    AutonomyLevel,
    ChatResponse,
    Message,
    RiskLevel,
    Role,
    StepStatus,
    Tool,
    ToolCall,
    default_requires_approval,
)
from swag_bot.registry import InMemoryToolRegistry
from tests.core.support import DenyPrompter, make_loop, plan_json, verdict
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore


def _step(
    step_id: str,
    title: str,
    *,
    instruction: str = "",
    criteria: str = "the step is done",
    depends_on: list[str] | None = None,
    checks: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": step_id,
        "title": title,
        "instruction": instruction or title,
        "success_criteria": criteria,
    }
    if depends_on:
        payload["depends_on"] = depends_on
    if checks is not None:
        payload["checks"] = checks
    return payload


def _systems(llm: FakeLLMClient, prefix: str) -> list[list[Message]]:
    return [messages for messages in llm.messages if (messages[0].content or "").startswith(prefix)]


def test_hard_deny_does_not_prompt(tmp_path: Path) -> None:
    class _DenyPolicy:
        @property
        def autonomy(self) -> AutonomyLevel:
            return AutonomyLevel.AUTO

        def classify(self, action: ActionRequest) -> RiskLevel:
            return action.risk

        def requires_approval(self, action: ActionRequest) -> bool:
            return False

        def decide(self, action: ActionRequest) -> str:
            return "deny"

    prompter = AutoApprovePrompter()
    llm = FakeLLMClient(
        [
            plan_json([_step("write", "Write a note")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "note.txt", "content": "nope"},
                        )
                    ]
                )
            ),
            "could not write",
            verdict(False, "file missing", replan=False),
            "Blocked.",
        ]
    )
    sandbox = FakeSandbox(tmp_path / "work")
    loop = PlanDoVerifyLoop(
        llm=llm,
        sandbox=sandbox,
        memory=InMemoryMemoryStore(),
        policy=_DenyPolicy(),
        prompter=prompter,
        max_attempts=1,
    )
    plan = loop.run("write a note")
    assert plan.steps[0].status is StepStatus.FAILED
    assert prompter.prompts == []
    assert loop.action_log[0].approved is False
    assert loop.action_log[0].approver == "policy"
    assert not (sandbox.workdir / "note.txt").exists()


def test_scripted_plan_reads_a_file_and_logs_the_action(tmp_path: Path) -> None:
    loop, llm, sandbox, memory = make_loop(
        tmp_path,
        [
            plan_json([_step("read", "Read the note", criteria="observation includes hello")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "note.txt"})]
                )
            ),
            "the file says hello",
            verdict(True, "saw hello"),
            "Read the note.",
        ],
    )
    sandbox.write_file("note.txt", "hello")
    plan = loop.run("read the note")
    assert [step.status for step in plan.steps] == [StepStatus.DONE]
    assert plan.steps[0].instruction.endswith("Success criteria: observation includes hello")
    assert loop.results["read"].verified is True
    assert loop.results["read"].evidence_ids
    assert sandbox.read_file("note.txt") == "hello"
    assert len(loop.action_log) == 1
    entry = loop.action_log[0]
    assert entry.approved is True
    assert entry.approver == "policy"
    assert entry.action.kind == ActionKind.READ_FILE.value
    assert entry.action.risk is RiskLevel.READ
    assert entry.autonomy is AutonomyLevel.ASK_RISKY
    assert memory.search("Read the note")
    assert "Read the note." in loop.summary_text
    offered = llm.tools[1]
    assert offered is not None
    assert {tool.name for tool in offered} >= {"read_file", "write_file", "run_shell"}


def test_retry_then_pass(tmp_path: Path) -> None:
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("only", "Do the work")]),
            "not yet",
            verdict(False, "missing file", replan=False),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "done.txt", "content": "ok"},
                        )
                    ]
                )
            ),
            "now it is done",
            verdict(True, "present"),
            "Recovered.",
        ],
        max_attempts=2,
    )
    plan = loop.run("finish the work")
    assert plan.steps[0].status is StepStatus.DONE
    attempts = _systems(llm, EXECUTOR_PREFIX)
    assert len(attempts) >= 2
    assert "missing file" in (attempts[1][-1].content or "")


def test_replan_replaces_a_failed_approach(tmp_path: Path) -> None:
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("a", "Try A")]),
            "nope",
            verdict(False, "wrong approach", replan=True),
            plan_json(
                [
                    _step(
                        "b",
                        "Try B",
                        checks=[{"id": "ran", "kind": "command", "command": "true"}],
                    )
                ]
            ),
            "ok",
            verdict(True, "B works"),
            "Used the second approach.",
        ],
        max_steps=4,
        max_attempts=2,
    )
    plan = loop.run("get it done")
    by_id = {step.id: step.status for step in plan.steps}
    assert by_id == {"a": StepStatus.FAILED, "b": StepStatus.DONE}


def test_replan_stops_when_the_step_budget_is_full(tmp_path: Path) -> None:
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("a", "Only step")]),
            "nope",
            verdict(False, "wrong approach", replan=True),
            "should not be asked",
        ],
        max_steps=1,
        max_attempts=2,
    )
    plan = loop.run("one step only")
    assert [step.status for step in plan.steps] == [StepStatus.FAILED]
    assert len(_systems(llm, PLANNER_PREFIX)) == 1


def test_approval_denied_does_not_write(tmp_path: Path) -> None:
    denier = DenyPrompter()
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("w", "Write a note", criteria="note.txt contains hello")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "note.txt", "content": "hello"},
                        )
                    ]
                )
            ),
            "could not write",
            verdict(False, "not written", replan=False),
            "Blocked.",
        ],
        prompter=denier,
        max_attempts=1,
    )
    plan = loop.run("write the note")
    assert plan.steps[0].status is StepStatus.FAILED
    assert not (sandbox.workdir / "note.txt").exists()
    assert len(denier.prompts) == 1
    assert denier.prompts[0].risk is RiskLevel.WRITE
    assert loop.action_log[0].approved is False
    assert loop.action_log[0].approver == "user"
    assert loop.action_log[0].outcome == "denied"


def test_auto_approves_writes_without_a_prompt(tmp_path: Path) -> None:
    prompter = AutoApprovePrompter()
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("w", "Write a note")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "note.txt", "content": "hello"},
                        )
                    ]
                )
            ),
            "wrote it",
            verdict(True, "file exists"),
            "Wrote the note.",
        ],
        autonomy=AutonomyLevel.AUTO,
        prompter=prompter,
        max_attempts=1,
    )
    plan = loop.run("write hello")
    assert plan.steps[0].status is StepStatus.DONE
    assert sandbox.read_file("note.txt") == "hello"
    assert prompter.prompts == []
    assert loop.action_log[0].approver == "auto"
    assert loop.action_log[0].approved is True


def test_ask_always_prompts_for_reads(tmp_path: Path) -> None:
    prompter = AutoApprovePrompter()
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("r", "Read")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "note.txt"})]
                )
            ),
            "hello",
            verdict(True),
            "done",
        ],
        autonomy=AutonomyLevel.ASK_ALWAYS,
        prompter=prompter,
        max_attempts=1,
    )
    sandbox.write_file("note.txt", "hello")
    loop.run("read it")
    assert len(prompter.prompts) == 1
    assert loop.action_log[0].approver == "user"


def test_dry_run_does_not_execute(tmp_path: Path) -> None:
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [plan_json([_step("a", "Think"), _step("b", "Act", depends_on=["a"])])],
    )
    plan = loop.run("plan only", dry_run=True)
    assert [step.status for step in plan.steps] == [StepStatus.PENDING, StepStatus.PENDING]
    assert loop.action_log == []
    assert len(llm.messages) == 1
    assert "Dry run" in loop.summary_text
    assert loop.results == {}


def test_failed_step_skips_dependents(tmp_path: Path) -> None:
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json(
                [
                    _step("a", "First"),
                    _step("b", "Second", depends_on=["a"]),
                ]
            ),
            "no",
            verdict(False, "failed the check", replan=False),
            "summary",
        ],
        max_attempts=1,
    )
    plan = loop.run("two steps")
    assert [step.status for step in plan.steps] == [StepStatus.FAILED, StepStatus.SKIPPED]
    assert len(_systems(llm, EXECUTOR_PREFIX)) == 1
    assert len(_systems(llm, VERIFIER_PREFIX)) == 1
    assert "dependency" in loop.results["b"].observation.lower()


def test_cycle_fails_both_steps(tmp_path: Path) -> None:
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json(
                [
                    _step("a", "A", depends_on=["b"]),
                    _step("b", "B", depends_on=["a"]),
                ]
            ),
            "summary",
        ],
    )
    plan = loop.run("cycle")
    assert [step.status for step in plan.steps] == [StepStatus.FAILED, StepStatus.FAILED]
    assert len(_systems(llm, EXECUTOR_PREFIX)) == 0
    assert len(_systems(llm, SUMMARIZER_PREFIX)) == 1
    assert "cycle" in (loop.results["a"].error or "").lower()


def test_max_steps_truncates_the_plan(tmp_path: Path) -> None:
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json(
                [
                    _step("a", "A"),
                    _step("b", "B"),
                    _step("c", "C"),
                ]
            )
        ],
        max_steps=1,
    )
    plan = loop.run("too many", dry_run=True)
    assert [step.id for step in plan.steps] == ["a"]


def test_parallel_independent_steps_run_tools_together(tmp_path: Path) -> None:
    registry = InMemoryToolRegistry()
    state = {"current": 0, "max": 0}
    lock = threading.Lock()

    def slow() -> str:
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.2)
        with lock:
            state["current"] -= 1
        return "ok"

    registry.register(Tool(name="slow", description="overlap with the sibling step"), slow)

    class RoutingLLM(FakeLLMClient):
        def chat(self, messages, *, tools=None, model=None):  # type: ignore[no-untyped-def]
            self.messages.append(list(messages))
            self.tools.append(tools)
            self.models.append(model)
            system = messages[0].content or ""
            if system.startswith(PLANNER_PREFIX):
                return ChatResponse(
                    message=Message.assistant(
                        plan_json([_step("a", "A"), _step("b", "B")])
                    )
                )
            if system.startswith(VERIFIER_PREFIX):
                return ChatResponse(message=Message.assistant(verdict(True, "ok")))
            if system.startswith(SUMMARIZER_PREFIX):
                return ChatResponse(message=Message.assistant("Both finished."))
            if any(message.role is Role.TOOL for message in messages):
                return ChatResponse(message=Message.assistant("finished"))
            return ChatResponse(
                message=Message.assistant(
                    tool_calls=[ToolCall(id="t", name="slow", arguments={})]
                )
            )

    llm = RoutingLLM()
    from tests.fakes import FakeSandbox, InMemoryMemoryStore

    loop = PlanDoVerifyLoop(
        llm=llm,
        sandbox=FakeSandbox(tmp_path / "work"),
        memory=InMemoryMemoryStore(),
        policy=_AutoPolicy(),
        prompter=AutoApprovePrompter(),
        tools=registry,
        concurrency=2,
        max_attempts=1,
    )
    plan = loop.run("do both")
    assert {step.status for step in plan.steps} == {StepStatus.DONE}
    assert state["max"] == 2
    assert len(loop.action_log) == 2
    assert all(entry.approved for entry in loop.action_log)


def test_destructive_risk_is_not_lowered(tmp_path: Path) -> None:
    prompter = AutoApprovePrompter()
    loop, _llm, sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("rm", "Clean")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(id="c1", name="run_shell", arguments={"command": "rm -rf build"})
                    ]
                )
            ),
            "removed",
            verdict(True, "gone"),
            "done",
        ],
        prompter=prompter,
        max_attempts=1,
    )
    loop.policy = _LoweringPolicy()
    plan = loop.run("clean the build")
    assert plan.steps[0].status is StepStatus.DONE
    assert sandbox.commands == ["rm -rf build"]
    assert loop.action_log[0].action.risk is RiskLevel.DESTRUCTIVE
    assert len(prompter.prompts) == 1


def test_secrets_are_redacted_in_the_action_log(tmp_path: Path) -> None:
    seen: list[str] = []
    registry = InMemoryToolRegistry()

    def use_secret(api_key: str, note: str) -> str:
        seen.append(api_key)
        return f"used {api_key} {note}"

    registry.register(Tool(name="use_secret", description="takes a key"), use_secret)
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            plan_json([_step("s", "Call")]),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="use_secret",
                            arguments={"api_key": "super-secret-value", "note": "token=abc"},
                        )
                    ]
                )
            ),
            "called",
            verdict(True),
            "done",
        ],
        autonomy=AutonomyLevel.AUTO,
        tools=registry,
        max_attempts=1,
    )
    loop.run("use the key")
    assert seen == ["super-secret-value"]
    logged = json.dumps(loop.action_log[0].model_dump(mode="json"))
    assert "super-secret-value" not in logged
    assert "abc" not in logged
    assert loop.action_log[0].action.arguments["api_key"] == "[redacted]"


def test_fenced_plan_json_and_unknown_tool(tmp_path: Path) -> None:
    fenced = "```json\n" + plan_json([_step("a", "Look")]) + "\n```"
    loop, _llm, _sandbox, _memory = make_loop(
        tmp_path,
        [
            fenced,
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[ToolCall(id="c1", name="missing_tool", arguments={})]
                )
            ),
            "no such tool",
            verdict(True, "reported the missing tool"),
            "done",
        ],
        max_attempts=1,
    )
    plan = loop.run("look around")
    assert plan.steps[0].id == "a"
    # The model said the step passed, but the tool never ran. That is a failure.
    assert plan.steps[0].status is StepStatus.FAILED
    assert loop.results["a"].evidence_ids
    assert "unknown tool" in (loop.results["a"].error or "")
    assert loop.action_log[0].approved is False
    assert loop.action_log[0].evidence_id
    assert "unknown tool" in (loop.action_log[0].outcome or "")


def test_unreadable_model_falls_back_to_one_step(tmp_path: Path) -> None:
    loop, llm, _sandbox, _memory = make_loop(
        tmp_path,
        ["not json", "still not json", "I tried", verdict(False, "no", replan=False), "summary"],
        max_attempts=1,
    )
    plan = loop.run("do the thing")
    assert len(plan.steps) == 1
    assert plan.steps[0].id == "step-1"
    assert plan.steps[0].status is StepStatus.FAILED
    assert len(_systems(llm, PLANNER_PREFIX)) == 2


class _AutoPolicy:
    @property
    def autonomy(self) -> AutonomyLevel:
        return AutonomyLevel.AUTO

    def classify(self, action: ActionRequest) -> RiskLevel:
        return action.risk

    def requires_approval(self, action: ActionRequest) -> bool:
        return default_requires_approval(self.autonomy, action.risk)


class _LoweringPolicy:
    """Illegally lowers every action, including destructive ones."""

    @property
    def autonomy(self) -> AutonomyLevel:
        return AutonomyLevel.ASK_RISKY

    def classify(self, action: ActionRequest) -> RiskLevel:
        return RiskLevel.READ

    def requires_approval(self, action: ActionRequest) -> bool:
        return action.risk is not RiskLevel.READ
