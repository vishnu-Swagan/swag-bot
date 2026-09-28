"""Rehearsal failures from a fresh Linux home with a local model.

Each test scripts the model. A false success is exit code 0 when the file is
wrong or the required command output was never shown.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from swag_bot.config import MemorySettings, Settings
from swag_bot.core.cli import execute_goal
from swag_bot.core.display import TaskListView
from swag_bot.core.executor import StepExecutor
from swag_bot.core.goal_checks import derive_goal_checks
from swag_bot.core.parsing import PlanParseError
from swag_bot.core.planner import Planner
from swag_bot.core.tools import (
    normalize_written_text,
    register_builtin_tools,
    rewrite_python_command,
)
from swag_bot.interfaces import (
    AutonomyLevel,
    ChatResponse,
    MemoryItem,
    Message,
    Step,
    TaskPlan,
    ToolCall,
)
from swag_bot.registry import InMemoryToolRegistry
from tests.core.support import StaticPolicy, plan_json, verdict
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore

GOAL = (
    "Write fizzbuzz.py that prints FizzBuzz for the numbers 1 to 15, "
    "one per line. Run it with python3 and check that the last line is FizzBuzz."
)

_CORRECT = """\
def label(n: int) -> str:
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return str(n)

for i in range(1, 16):
    print(label(i))
"""

_FLAT = 'print("".join(str(i) for i in range(1, 101)))\n'
_CLAIM = "The script was run with python3, and the last line printed was FizzBuzz."


def test_goal_checks_cover_run_last_line_and_line_count() -> None:
    checks = {item.id: item for item in derive_goal_checks(GOAL)}
    assert checks["goal-file"].path == "fizzbuzz.py"
    assert checks["goal-run"].command == "python3 fizzbuzz.py"
    assert checks["goal-last-line"].stdout_last_line == "FizzBuzz"
    assert checks["goal-lines"].stdout_line_count == 15


def test_strict_planner_rejects_a_write_only_fizzbuzz_step() -> None:
    write_only = plan_json(
        [
            {
                "id": "write",
                "title": "Write the fizzbuzz code into fizzbuzz.py",
                "instruction": "Write the fizzbuzz code into fizzbuzz.py",
            }
        ]
    )
    accepted = plan_json(
        [
            {
                "id": "fizz",
                "title": "Write, run, and check fizzbuzz.py",
                "instruction": (
                    "Write fizzbuzz.py, run it with python3, "
                    "and check that the last line is FizzBuzz."
                ),
            }
        ]
    )
    llm = FakeLLMClient([write_only, accepted])
    plan = Planner(llm, strict=True).create(GOAL, max_steps=3)
    assert [step.id for step in plan.steps] == ["fizz"]
    feedback = llm.messages[1][1].content or ""
    assert "run or execute" in feedback


def test_strict_planner_stops_when_every_plan_omits_the_run() -> None:
    write_only = plan_json(
        [
            {
                "id": "write",
                "title": "Write the fizzbuzz code into fizzbuzz.py",
                "instruction": "Write the fizzbuzz code into fizzbuzz.py",
            }
        ]
    )
    llm = FakeLLMClient([write_only, write_only])
    with pytest.raises(PlanParseError, match="run or execute"):
        Planner(llm, strict=True).create(GOAL, max_steps=3)


def test_flat_output_is_not_a_success(tmp_path: Path) -> None:
    result = _run(tmp_path, _FLAT, run="python3 fizzbuzz.py")
    assert result.exit_code != 0
    assert "Goal not met." in result.summary
    assert "Goal met." not in result.summary
    assert "(unverified)" in result.summary
    assert _CLAIM in result.summary


def test_redirected_verify_does_not_count(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "print(1)\nprint(2)\nprint(3)\n",
        run="python3 fizzbuzz.py > out.txt",
        checks=[{"id": "ran", "kind": "exit_code", "expected_exit": 0}],
    )
    assert result.exit_code != 0
    assert "Goal not met." in result.summary
    text = (tmp_path / "out" / "fizzbuzz.py").read_text(encoding="utf-8")
    assert text.endswith("\n")


def test_correct_fizzbuzz_exits_zero_with_cited_evidence(tmp_path: Path) -> None:
    result = _run(tmp_path, _CORRECT, run="python3 fizzbuzz.py")
    assert result.exit_code == 0, result.summary
    assert "Goal met." in result.summary
    assert "(unverified)" not in result.summary
    assert "evidence:" in result.summary
    assert "ev-" in result.summary
    script = (tmp_path / "out" / "fizzbuzz.py").read_text(encoding="utf-8")
    assert script.endswith("\n")
    assert "\\n" not in script


def test_literal_newline_sequences_become_real_lines() -> None:
    raw = "for i in range(1, 101):\\n    if i % 3 == 0:\\n        print(i)"
    text = normalize_written_text("fizzbuzz.py", raw)
    assert "\\n" not in text
    assert text.startswith("for i in range(1, 101):\n    if i % 3 == 0:\n")
    assert text.endswith("\n")
    assert normalize_written_text("notes.txt", "hello") == "hello\n"
    assert normalize_written_text("notes.txt", "") == ""


def test_retry_rewrites_before_it_runs_again(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "box")
    registry = InMemoryToolRegistry()
    register_builtin_tools(registry, sandbox)
    llm = FakeLLMClient(
        [
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="w1",
                            name="write_file",
                            arguments={"path": "bad.py", "content": "print(1)"},
                        )
                    ]
                )
            ),
            "wrote it",
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="r1",
                            name="run_shell",
                            arguments={"command": "python3 bad.py"},
                        )
                    ]
                )
            ),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="w2",
                            name="write_file",
                            arguments={"path": "bad.py", "content": "print(2)"},
                        )
                    ]
                )
            ),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="r2",
                            name="run_shell",
                            arguments={"command": "python3 bad.py"},
                        )
                    ]
                )
            ),
            "rewrote it",
        ]
    )
    executor = StepExecutor(
        llm=llm,
        tools=registry,
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        memory=InMemoryMemoryStore(),
        memory_mode="off",
    )
    step = Step(id="s", title="Write bad.py", instruction="Write bad.py and run it")
    executor.execute(step, attempt=1, feedback=None)
    assert executor.note_failed_writes() == ["bad.py"]
    executor.execute(step, attempt=2, feedback="the previous file failed")
    assert sandbox.commands == ["python3 bad.py"]
    assert any("rewrite" in line for line in executor.trace_for("s"))
    assert sandbox.read_file("bad.py") == "print(2)\n"


def test_unrelated_squares_memory_is_not_injected() -> None:
    from swag_bot.core.memory_journal import relevant_memories as recall

    squares = MemoryItem(
        id="squares",
        content="wrote squares.csv with one square per line",
        metadata={"goal": "print squares of 1 to 10", "workspace": "/tmp/squares"},
    )
    fizz = MemoryItem(
        id="fizz",
        content="fizzbuzz.py printed FizzBuzz",
        metadata={"goal": GOAL, "workspace": "/tmp/fizz"},
    )
    chosen = recall([squares, fizz], GOAL, workspace="/tmp/fizz")
    assert [item.id for item in chosen] == ["fizz"]


def test_bare_python_is_rewritten_when_python_is_missing() -> None:
    def which(name: str) -> str | None:
        if name == "python3":
            return "/usr/bin/python3"
        return None

    assert rewrite_python_command("python fizzbuzz.py", which=which) == "python3 fizzbuzz.py"
    assert rewrite_python_command("python3 fizzbuzz.py", which=which) == "python3 fizzbuzz.py"
    assert rewrite_python_command("echo python", which=which) == "echo python"


def test_live_notes_print_once_outside_the_table() -> None:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, no_color=True, highlight=False, width=100)
    view = TaskListView(console)
    plan = TaskPlan(
        goal=GOAL,
        steps=[Step(id="write", title="Write the fizzbuzz code into fizzbuzz.py")],
    )
    approval = "Allow this action? write fizzbuzz.py with one number per line"
    status = "[running] write Write the fizzbuzz code into fizzbuzz.py"
    with view:
        view.update(plan)
        view.note(approval)
        view.note(status)
    text = buf.getvalue()
    assert text.count(approval) == 1
    assert text.count(status) == 1
    assert approval in text


def _run(
    tmp_path: Path,
    content: str,
    *,
    run: str,
    checks: list[dict[str, object]] | None = None,
):
    step: dict[str, object] = {
        "id": "write",
        "title": "Write the fizzbuzz code into fizzbuzz.py",
        "instruction": "Write fizzbuzz.py, run it with python3, and check the last line.",
        "checks": checks if checks is not None else [],
    }
    calls = [
        ToolCall(id="w", name="write_file", arguments={"path": "fizzbuzz.py", "content": content})
    ]
    if run:
        calls.append(ToolCall(id="r", name="run_shell", arguments={"command": run}))
    llm = FakeLLMClient(
        [
            plan_json([step]),
            ChatResponse(message=Message.assistant(tool_calls=calls)),
            "Wrote fizzbuzz.py.",
            verdict(True, _CLAIM),
            _CLAIM,
        ]
    )
    return execute_goal(
        GOAL,
        client=llm,
        autonomy=AutonomyLevel.AUTO,
        output_dir=tmp_path / "out",
        max_attempts=1,
        settings=Settings(
            autonomy=AutonomyLevel.AUTO,
            memory=MemorySettings(mode="off"),
        ),
    )
