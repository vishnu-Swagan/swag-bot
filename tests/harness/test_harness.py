"""Small-model harness: probe, scaffold, tool narrowing, and escalation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.config import FallbackModelSettings, ModelBudgetSettings, ModelSettings, Settings
from swag_bot.core.executor import StepExecutor
from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.core.planner import Planner
from swag_bot.core.prompts import PLANNER_SYSTEM, PLANNER_SYSTEM_TINY
from swag_bot.core.scaffold import StepEscalation
from swag_bot.core.tools import register_builtin_tools
from swag_bot.harness.budget import EscalationBudget
from swag_bot.harness.checks import deterministic_precheck
from swag_bot.harness.probe import (
    CapabilityReport,
    choose_scaffold,
    context_from_show,
    profile_model,
)
from swag_bot.harness.session import prepare_harness
from swag_bot.harness.sizing import (
    estimate_cost_usd,
    parameter_billions,
    request_timeout_seconds,
)
from swag_bot.harness.tools import order_tools
from swag_bot.interfaces import (
    AutonomyLevel,
    ChatResponse,
    Message,
    Step,
    StepResult,
    StepStatus,
    Tool,
    ToolCall,
)
from swag_bot.registry import InMemoryToolRegistry
from tests.core.support import StaticPolicy, plan_json, verdict
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore

_TASKS = Path(__file__).resolve().parents[2] / "evals" / "small_models" / "tasks.json"


class _ProbeClient:
    """Scripted model for the probe. Not an Ollama client, so nothing is copied."""

    def __init__(
        self,
        json_text: str,
        call: ToolCall | None,
        show: dict[str, object] | None,
    ) -> None:
        self.json_text = json_text
        self.call = call
        self.show = show
        self.schemas: list[object] = []

    def complete_structured(
        self,
        messages: list[Message],
        schema: dict[str, object],
        *,
        model: str | None = None,
    ) -> ChatResponse:
        del messages, model
        self.schemas.append(schema)
        return ChatResponse(message=Message.assistant(self.json_text))

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[Tool] | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        del messages, tools, model
        if self.call is None:
            return ChatResponse(message=Message.assistant("no tool"))
        return ChatResponse(message=Message.assistant("", [self.call]))

    def show_model(
        self,
        name: str | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, object] | None:
        del name, timeout
        return self.show


def test_size_timeout_and_scaffold_choice() -> None:
    assert parameter_billions("qwen2.5:3b") == 3
    assert parameter_billions("qwen2.5:0.5b") == 0.5
    assert parameter_billions("mixtral:8x7b") == 56
    assert parameter_billions("llama3.2") == 3
    assert request_timeout_seconds("ollama", "qwen2.5:3b", None) == 120
    assert request_timeout_seconds("ollama", "qwen2.5:7b", None) == 180
    assert request_timeout_seconds("ollama", "qwen2.5:7b", None, num_predict=1024) == 180
    assert request_timeout_seconds("ollama", "qwen2.5:7b", None, num_predict=4096) == 439.6
    assert request_timeout_seconds("ollama", "qwen2.5:7b", 90) == 90
    assert request_timeout_seconds("openai", "gpt-4o-mini", None) is None
    assert estimate_cost_usd("ollama") == 0
    assert estimate_cost_usd("openai") > 0
    assert (
        choose_scaffold(
            model="qwen2.5:3b",
            json_adherence=1.0,
            tool_call_reliability=1.0,
            context_tokens=32768,
        )
        == "tiny"
    )
    assert (
        choose_scaffold(
            model="qwen2.5:7b",
            json_adherence=1.0,
            tool_call_reliability=1.0,
            context_tokens=32768,
        )
        == "standard"
    )
    assert (
        choose_scaffold(
            model="qwen2.5:32b",
            json_adherence=1.0,
            tool_call_reliability=1.0,
            context_tokens=32768,
        )
        == "frontier"
    )
    assert (
        choose_scaffold(
            model="qwen2.5:7b",
            json_adherence=0.0,
            tool_call_reliability=1.0,
            context_tokens=32768,
        )
        == "tiny"
    )
    assert context_from_show({"model_info": {"qwen2.context_length": 32768}}) == 32768
    assert context_from_show({"parameters": "num_ctx 8192"}) == 8192


def test_probe_caches_a_passing_small_model(tmp_path: Path) -> None:
    client = _ProbeClient(
        '{"ok": true, "n": 4}',
        ToolCall(id="c1", name="echo_token", arguments={"token": "ping"}),
        {"model_info": {"qwen2.context_length": 32768}},
    )
    cache = tmp_path / "capability.json"
    report = profile_model(
        client=client,
        provider="ollama",
        model="qwen2.5:3b",
        cache_path=cache,
    )
    assert report.scaffold == "tiny"
    assert report.json_adherence == 1
    assert report.tool_call_reliability == 1
    assert report.tool_call_mode == "called"
    assert report.context_tokens == 32768
    assert report.supports_json_schema is True
    assert report.cached is False
    assert client.schemas and "short-id" not in json.dumps(client.schemas)
    again = profile_model(
        client=_ProbeClient("not json", None, None),
        provider="ollama",
        model="qwen2.5:3b",
        cache_path=cache,
    )
    assert again.cached is True
    assert again.json_adherence == 1


def test_tiny_prompts_have_no_sample_id() -> None:
    assert "short-id" in PLANNER_SYSTEM
    assert "short-id" not in PLANNER_SYSTEM_TINY
    assert "what this step does" not in PLANNER_SYSTEM_TINY


def test_strict_planner_collapses_a_one_file_goal_to_one_step() -> None:
    split = plan_json(
        [
            {"id": "get_code", "title": "Get the code", "instruction": "Observe fib.py."},
            {"id": "run_script", "title": "Run it", "instruction": "Execute fib.py."},
            {"id": "check_output", "title": "Check", "instruction": "Read the output."},
        ]
    )
    one = plan_json(
        [
            {
                "id": "fib",
                "title": "Write and run fib.py",
                "instruction": (
                    "Write fib.py so it prints the 10th Fibonacci number, "
                    "then run it and check the output."
                ),
            }
        ]
    )
    llm = FakeLLMClient([split, one])
    plan = Planner(llm, strict=True).create(
        "Write fib.py that prints the 10th Fibonacci number, run it, and check the output.",
        max_steps=3,
    )
    assert [step.id for step in plan.steps] == ["fib"]
    feedback = llm.messages[1][1].content or ""
    assert "exactly one step" in feedback


def test_strict_planner_rejects_a_step_that_never_says_to_write() -> None:
    vague = plan_json(
        [
            {
                "id": "write_fib",
                "title": "Write fib.py and execute it",
                "instruction": "Use the Fibonacci function in fib.py and check the output.",
            }
        ]
    )
    clear = plan_json(
        [
            {
                "id": "fib",
                "title": "Write and run fib.py",
                "instruction": (
                    "Write fib.py so it prints the 10th Fibonacci number, "
                    "then run it and check the output."
                ),
            }
        ]
    )
    llm = FakeLLMClient([vague, clear])
    plan = Planner(llm, strict=True).create(
        "Write fib.py that prints the 10th Fibonacci number, run it, and check the output.",
        max_steps=3,
    )
    assert [step.id for step in plan.steps] == ["fib"]
    assert "write the file" in (llm.messages[1][1].content or "")


def test_strict_planner_keeps_a_two_file_goal_split() -> None:
    split = plan_json(
        [
            {"id": "costs", "title": "Write costs", "instruction": "Write costs.csv."},
            {"id": "total", "title": "Write and run", "instruction": "Write total.py and run it."},
        ]
    )
    llm = FakeLLMClient([split])
    plan = Planner(llm, strict=True).create(
        "Write costs.csv with two rows, write total.py that prints their sum, and run total.py.",
        max_steps=3,
    )
    assert [step.id for step in plan.steps] == ["costs", "total"]


def test_probe_module_imports_before_the_core_package() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from swag_bot.harness.probe import choose_scaffold; "
            "print(choose_scaffold(model='qwen2.5:3b', json_adherence=1, "
            "tool_call_reliability=1, context_tokens=32768))",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "tiny"


def test_strict_planner_rejects_a_copied_sample_then_accepts_a_real_plan() -> None:
    copied = plan_json(
        [
            {
                "id": "short-id",
                "title": "what this step does",
                "instruction": "how to do it with the available tools",
            }
        ]
    )
    real = plan_json(
        [
            {
                "id": "fib",
                "title": "Write and run fib.py",
                "instruction": (
                    "Write fib.py and run it with python.\nDone when: it prints a number."
                ),
            }
        ]
    )
    llm = FakeLLMClient([copied, real])
    plan = Planner(llm, strict=True, system=PLANNER_SYSTEM_TINY).create(
        "write fib.py and run it",
        max_steps=3,
    )
    assert [step.id for step in plan.steps] == ["fib"]
    assert len(llm.messages) == 2
    assert "short-id" not in (llm.messages[1][1].content or "")


def test_strict_planner_rejects_an_over_split_plan() -> None:
    too_many = plan_json(
        [
            {"id": f"s{i}", "title": f"Step {i}", "instruction": f"Do part {i}."}
            for i in range(4)
        ]
    )
    one = plan_json(
        [{"id": "fib", "title": "Write and run", "instruction": "Write fib.py and run it."}]
    )
    llm = FakeLLMClient([too_many, one])
    plan = Planner(llm, strict=True).create("write fib.py and run it", max_steps=3)
    assert [step.id for step in plan.steps] == ["fib"]
    feedback = llm.messages[1][1].content or ""
    assert "4 steps" in feedback


def test_auto_harness_leaves_a_fake_client_alone() -> None:
    fake = FakeLLMClient(["unused"])
    prepared = prepare_harness(Settings(), fake)
    assert prepared.scaffold is None
    assert prepared.escalation is None
    assert prepared.note == ""
    assert fake.messages == []


def test_tiny_harness_on_a_fake_narrows_tools_and_blocks_a_second_write(tmp_path: Path) -> None:
    settings = Settings(model=ModelSettings(provider="ollama", model="qwen2.5:3b", harness="tiny"))
    prepared = prepare_harness(settings, FakeLLMClient([]))
    assert prepared.scaffold is not None
    assert prepared.scaffold.max_steps == 3
    assert prepared.scaffold.guard_repeat_writes is True
    assert prepared.scaffold.retry_blank_turns is True
    scaffold = prepared.scaffold
    assert scaffold.pick_tools is not None
    step = Step(
        id="fib",
        title="Write fib.py",
        instruction="Write fib.py then run it with python.",
    )
    ordered = order_tools(
        step,
        [Tool(name="read_file"), Tool(name="write_file"), Tool(name="run_shell")],
    )
    assert [tool.name for tool in ordered[:2]] == ["write_file", "run_shell"]
    first = scaffold.pick_tools(step, ordered, 0, set())
    assert [tool.name for tool in first] == ["write_file"]
    second = scaffold.pick_tools(step, ordered, 1, {"write_file"})
    assert [tool.name for tool in second] == ["run_shell"]

    llm = FakeLLMClient(
        [
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="w1",
                            name="write_file",
                            arguments={"path": "fib.py", "content": "print(1)\n"},
                        ),
                        ToolCall(
                            id="w2",
                            name="write_file",
                            arguments={"path": "fib.py", "content": "print(2)\n"},
                        ),
                    ]
                )
            ),
            "wrote it once",
        ]
    )
    sandbox = FakeSandbox(tmp_path / "work")
    tools = InMemoryToolRegistry()
    register_builtin_tools(tools, sandbox)
    executor = StepExecutor(
        llm=llm,
        tools=tools,
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        memory=InMemoryMemoryStore(),
        guard_repeat_writes=True,
        pick_tools=scaffold.pick_tools,
        max_tool_rounds=3,
    )
    result = executor.execute(step, attempt=1, feedback=None)
    assert sandbox.read_file("fib.py") == "print(1)\n"
    assert "Do not write it again" in result.observation or any(
        "Do not write it again" in line for line in executor.trace_for("fib")
    )
    shown = [tool.name for tools_sent in llm.tools if tools_sent for tool in tools_sent]
    assert shown[0] == "write_file"


def test_tiny_executor_retries_a_blank_reply(tmp_path: Path) -> None:
    step = Step(id="fib", title="Write fib.py", instruction="Write fib.py and run it.")
    llm = FakeLLMClient(
        [
            "",
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="w",
                            name="write_file",
                            arguments={"path": "fib.py", "content": "print(55)\n"},
                        )
                    ]
                )
            ),
            "Wrote fib.py.",
        ]
    )
    sandbox = FakeSandbox(tmp_path)
    tools = InMemoryToolRegistry()
    register_builtin_tools(tools, sandbox)
    executor = StepExecutor(
        llm=llm,
        tools=tools,
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        memory=InMemoryMemoryStore(),
        retry_blank_turns=True,
        max_tool_rounds=3,
    )
    result = executor.execute(step, attempt=1, feedback=None)
    assert sandbox.read_file("fib.py") == "print(55)\n"
    assert "empty" in (llm.messages[1][-1].content or "")
    assert "Wrote fib.py." in result.observation


def test_deterministic_check_fails_a_write_that_never_ran() -> None:
    step = Step(id="fib", title="Run fib", instruction="Write fib.py and run it with python.")
    result = StepResult(step_id="fib", status=StepStatus.VERIFYING)
    missed = deterministic_precheck(step, result, ["write_file: wrote fib.py"])
    assert missed is not None
    assert missed.passed is False
    ran = deterministic_precheck(
        step,
        result,
        ["write_file: wrote fib.py", "run_shell: exit_code=0 timed_out=false\nstdout:\n55\n"],
    )
    assert ran is not None
    assert ran.passed is True
    recovered = deterministic_precheck(
        step,
        result,
        [
            "run_shell: exit_code=127 timed_out=false",
            "run_shell: exit_code=0 timed_out=false\nstdout:\n55\n",
        ],
    )
    assert recovered is not None
    assert recovered.passed is True


def test_budget_allows_a_local_fallback_and_blocks_a_cloud_one() -> None:
    local = EscalationBudget(max_escalations=1, max_extra_seconds=180, max_cost_usd=0)
    assert local.allow(estimated_seconds=120, estimated_cost_usd=0) is True
    assert local.allow(estimated_seconds=10, estimated_cost_usd=0) is False
    cloud = EscalationBudget(max_escalations=1, max_extra_seconds=180, max_cost_usd=0)
    cloud_cost = estimate_cost_usd("openai")
    assert cloud.allow(estimated_seconds=20, estimated_cost_usd=cloud_cost) is False
    tight = EscalationBudget(max_escalations=2, max_extra_seconds=30, max_cost_usd=1)
    assert tight.allow(estimated_seconds=120, estimated_cost_usd=0) is False


def test_failing_step_escalates_to_the_stronger_model(tmp_path: Path) -> None:
    primary = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "fib",
                        "title": "Write and run fib.py",
                        "instruction": "Write fib.py and run it with python.",
                    }
                ]
            ),
            "I wrote the file.",
            verdict(False, "the script was not run"),
            "The stronger model ran fib.py.",
        ]
    )
    fallback = FakeLLMClient(
        [
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(
                            id="w",
                            name="write_file",
                            arguments={"path": "fib.py", "content": "print(55)\n"},
                        )
                    ]
                )
            ),
            ChatResponse(
                message=Message.assistant(
                    tool_calls=[
                        ToolCall(id="r", name="run_shell", arguments={"command": "python fib.py"})
                    ]
                )
            ),
            "printed 55",
        ]
    )
    settings = Settings(model=ModelSettings(harness="tiny", model="qwen2.5:3b"))
    prepared = prepare_harness(settings, FakeLLMClient([]))
    assert prepared.scaffold is not None
    budget = EscalationBudget(max_escalations=1, max_extra_seconds=180, max_cost_usd=0)
    escalation = StepEscalation(
        llm=fallback,
        model="qwen2.5:7b",
        allow=lambda: budget.allow(estimated_seconds=30, estimated_cost_usd=0),
        charge=budget.charge,
        label="ollama/qwen2.5:7b",
    )
    events: list[str] = []
    sandbox = FakeSandbox(tmp_path / "work")
    loop = PlanDoVerifyLoop(
        llm=primary,
        sandbox=sandbox,
        memory=InMemoryMemoryStore(),
        policy=StaticPolicy(AutonomyLevel.AUTO),
        prompter=AutoApprovePrompter(),
        max_steps=8,
        max_attempts=1,
        concurrency=1,
        scaffold=prepared.scaffold,
        model_escalation=escalation,
        on_event=lambda event: events.append(event.kind),
    )
    plan = loop.run("Write fib.py that prints 55 and run it.")
    assert plan.steps[0].status.value == "done"
    assert sandbox.read_file("fib.py") == "print(55)\n"
    assert any(command.endswith("fib.py") for command in sandbox.commands)
    assert "escalate" in events
    assert budget.used_escalations == 1
    assert fallback.models[0] == "qwen2.5:7b"


def test_configured_fallback_is_cost_gated() -> None:
    settings = Settings(
        model=ModelSettings(
            provider="ollama",
            model="qwen2.5:3b",
            harness="tiny",
            fallback=FallbackModelSettings(provider="openai", model="gpt-4o-mini"),
            budget=ModelBudgetSettings(max_cost_usd=0),
        )
    )
    prepared = prepare_harness(settings, FakeLLMClient([]))
    assert prepared.escalation is not None
    assert prepared.escalation.allow() is False
    local = Settings(
        model=ModelSettings(
            provider="ollama",
            model="qwen2.5:3b",
            harness="off",
        )
    )
    assert prepare_harness(local, FakeLLMClient([])).escalation is None


def test_task_list_has_twenty_messy_tasks() -> None:
    tasks = json.loads(_TASKS.read_text(encoding="utf-8"))
    assert len(tasks) == 20
    assert tasks[0]["id"] == "fib-py"
    ids = [task["id"] for task in tasks]
    assert len(ids) == len(set(ids))


def test_probe_command_prints_a_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from swag_bot.cli import app
    from tests.cli_output import visible

    report = CapabilityReport(
        provider="ollama",
        model="qwen2.5:3b",
        json_adherence=0.0,
        tool_call_reliability=0.0,
        tool_call_mode="none",
        context_tokens=32768,
        supports_json_schema=True,
        scaffold="tiny",
        notes=["response was not JSON"],
        probed_at="2026-09-27T00:00:00+00:00",
    )

    def _profile(**kwargs: object) -> CapabilityReport:
        del kwargs
        return report

    monkeypatch.setattr("swag_bot.harness.probe.profile_model", _profile)
    runner = CliRunner()
    result = runner.invoke(app, ["model", "probe"])
    text = visible(result)
    assert result.exit_code == 0, text
    assert "scaffold: tiny" in text
    assert "json_adherence: 0.00" in text
    doctor = runner.invoke(app, ["doctor", "--probe"])
    doctor_text = visible(doctor)
    assert doctor.exit_code == 0, doctor_text
    assert "scaffold: tiny" in doctor_text
    assert "model.harness" in doctor_text
