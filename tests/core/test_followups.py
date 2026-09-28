"""Follow-ups from the real Ollama rehearsal of the false-success fixes."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from swag_bot.config import MemorySettings, Settings
from swag_bot.core.approvals import approval_scope, remember_approved_command
from swag_bot.core.checks import CheckRunner
from swag_bot.core.cli import execute_goal
from swag_bot.core.display import TaskListView
from swag_bot.core.evidence import EvidenceLedger
from swag_bot.core.memory_journal import memory_relevance, relevant_memories
from swag_bot.core.summary import (
    clean_model_summary,
    filter_unbacked_claims,
    render_record,
    summarize,
)
from swag_bot.harness.sizing import local_num_predict
from swag_bot.interfaces import (
    AutonomyLevel,
    Check,
    CheckResult,
    Evidence,
    MemoryItem,
    Step,
    StepStatus,
    TaskPlan,
)
from swag_bot.models.errors import ModelError
from tests.core.support import DenyPrompter, StaticPolicy
from tests.fakes import FakeLLMClient, FakeSandbox

_ECHO = (
    "Wrote fizzbuzz.py and ran it with python3. "
    "Goal met. - **Met**: `fizzbuzz.py` exists. - **Met**: Command exited with expected status. "
    "Goal: Write `fizzbuzz.py` that prints FizzBuzz. Steps: - write done. Result: 2 done, 0 failed."
)
_FIZZ = "Write fizzbuzz.py that prints FizzBuzz for the numbers 1 to 15, one per line."


def test_local_predict_cap_and_timeout_follow_the_cap() -> None:
    assert Settings().model.num_predict == 1024
    assert local_num_predict("ollama", 4096, None) == 1024
    assert local_num_predict("ollama", 4096, 600) == 4096
    assert local_num_predict("openai", 4096, None) == 4096


def test_summary_keeps_two_sentences_and_drops_the_echo() -> None:
    assert clean_model_summary(_ECHO) == "Wrote fizzbuzz.py and ran it with python3."
    evidence = [Evidence(kind="tool", tool="run_shell", exit_code=0, ok=True, stdout="FizzBuzz\n")]
    checks = [
        CheckResult(
            check_id="goal-file",
            passed=True,
            evidence_ids=["ev-1"],
            detail="goal-file: fizzbuzz.py exists",
        )
    ]
    plan = TaskPlan(
        goal=_FIZZ,
        steps=[Step(id="write", title="Write fizzbuzz.py", status=StepStatus.DONE)],
    )
    text = summarize(FakeLLMClient([_ECHO]), plan, {}, goal_results=checks, evidence=evidence)
    assert text.count("Goal met.") == 1
    assert "Command exited with expected status" not in text
    assert "Wrote fizzbuzz.py and ran it with python3." in text


def test_a_true_last_line_is_not_marked_unverified() -> None:
    evidence = [Evidence(kind="tool", tool="run_shell", exit_code=0, ok=True, stdout="1\n15\n")]
    checks = [
        CheckResult(
            check_id="goal-last-line",
            passed=False,
            evidence_ids=["ev-1"],
            detail="last line is '15', expected 'FizzBuzz'",
        )
    ]
    sentence = "The script ran with python3, but the last line was '15'."
    assert filter_unbacked_claims(sentence, evidence, checks) == sentence
    contradicted = filter_unbacked_claims("The last line was FizzBuzz.", evidence, checks)
    assert contradicted.startswith("(unverified)")


def test_failed_checks_say_not_met_when_evidence_exists() -> None:
    plan = TaskPlan(goal=_FIZZ, steps=[])
    text = render_record(
        plan,
        {},
        goal_results=[
            CheckResult(
                check_id="goal-file",
                passed=False,
                evidence_ids=["ev-1"],
                detail="goal-file: fizzbuzz.py does not exist",
            ),
            CheckResult(
                check_id="goal-run",
                passed=False,
                evidence_ids=[],
                detail="goal-run: command never ran",
            ),
        ],
    )
    assert "- not met: goal-file: fizzbuzz.py does not exist" in text
    assert "- unverified: goal-file" not in text
    assert "- unverified: goal-run: command never ran" in text


def test_line_count_includes_blank_lines(tmp_path: Path) -> None:
    ledger = EvidenceLedger(directory=tmp_path / "ev")
    body = "\n".join(["1", "", "3", "", "5", "", "7", "", "9", "", "11", "", "13", "", "15"])
    ledger.record_tool(
        step_id="s",
        tool="run_shell",
        arguments={"command": "python3 fizzbuzz.py"},
        outcome=f"exit_code=0 timed_out=false\nstdout:\n{body}\nstderr:\n",
        approved=True,
    )
    runner = CheckRunner(sandbox=FakeSandbox(tmp_path), ledger=ledger)
    step = Step(
        id="s",
        title="count",
        instruction="count",
        checks=[Check(id="goal-lines", kind="stdout", stdout_line_count=15)],
    )
    result = runner.run(step)[0]
    assert result.passed, result.detail


def test_an_approved_command_is_not_prompted_again(tmp_path: Path) -> None:
    prompter = DenyPrompter()
    runner = CheckRunner(
        sandbox=FakeSandbox(tmp_path),
        ledger=EvidenceLedger(directory=tmp_path / "ev"),
        policy=StaticPolicy(AutonomyLevel.ASK_ALWAYS),
        prompter=prompter,
    )
    step = Step(
        id="swag-goal",
        title="Goal acceptance",
        instruction="run",
        checks=[
            Check(id="goal-run", kind="command", command="python3 fizzbuzz.py", expected_exit=0)
        ],
    )
    with approval_scope():
        remember_approved_command("python3   fizzbuzz.py")
        result = runner.run(step)[0]
    assert prompter.prompts == []
    assert result.passed, result.detail


def test_squares_numbers_do_not_match_fizzbuzz() -> None:
    squares = MemoryItem(
        id="squares",
        content="print squares from 1 to 10",
        metadata={"goal": "print squares of 1 to 10", "workspace": "/tmp/work"},
    )
    assert memory_relevance(_FIZZ, squares, workspace="/tmp/work") == 0
    assert relevant_memories([squares], _FIZZ, workspace="/tmp/work") == []
    weak = "fizzbuzz alpha beta gamma delta"
    item = MemoryItem(
        id="fizz",
        content="fizzbuzz",
        metadata={"goal": "fizzbuzz", "workspace": "/tmp/other"},
    )
    assert memory_relevance(weak, item, workspace="/tmp/work") == 0
    assert memory_relevance(weak, item, workspace="/tmp/other") == pytest.approx(0.2)
    assert relevant_memories([item], weak, workspace="/tmp/other") == [item]


def test_progress_lines_drop_markdown() -> None:
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True, highlight=False, width=100)
    view = TaskListView(console)
    view.note("[write-fizzbuzz] The file `fizzbuzz.py` has been **created**")
    text = buf.getvalue()
    assert "`" not in text
    assert "**" not in text
    assert "[write-fizzbuzz] The file fizzbuzz.py has been created" in text


def test_timeout_still_writes_an_honest_summary(tmp_path: Path) -> None:
    class TimeoutModel(FakeLLMClient):
        def chat(self, messages: object, **kwargs: object) -> object:
            del messages, kwargs
            raise ModelError("request to http://127.0.0.1:11434/api/chat timed out")

    out = tmp_path / "out"
    with pytest.raises(ModelError, match="timed out"):
        execute_goal(
            _FIZZ,
            client=TimeoutModel(),
            output_dir=out,
            settings=Settings(
                autonomy=AutonomyLevel.AUTO,
                memory=MemorySettings(mode="off"),
            ),
            memory_mode="off",
        )
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "Goal not met." in summary
    assert "timed out" in summary
    assert "not a success" in summary
    assert "Goal met." not in summary
    assert (out / ".swag" / "plan.json").is_file()
    assert (out / ".swag" / "run.jsonl").is_file()
