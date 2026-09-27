"""Behavior of the shared test doubles and the default tool registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.errors import NotImplementedYet, SandboxError
from swag_bot.interfaces import (
    ActionKind,
    ActionRequest,
    AutonomyLevel,
    ChatResponse,
    CommandResult,
    Message,
    PermissionPolicy,
    RiskLevel,
    StepStatus,
    Tool,
    ToolCall,
    default_requires_approval,
)
from swag_bot.mcp import build_mcp_client
from swag_bot.memory import build_memory_store
from swag_bot.models import build_llm_client
from swag_bot.registry import InMemoryToolRegistry
from swag_bot.safety import build_permission_policy, build_prompter, build_sandbox
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore


def test_fake_llm_scripts_responses() -> None:
    client = FakeLLMClient(["hello", ChatResponse(message=Message.assistant("next"))])
    assert client.complete("first") == "hello"
    second = client.chat([Message.user("second")])
    assert second.message.content == "next"
    assert len(client.messages) == 2
    empty = client.chat([Message.user("third")])
    assert empty.message.content == ""


def test_fake_sandbox_files_and_recorded_commands(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "work")
    sandbox.write_file("dir/note.txt", "hi")
    assert sandbox.read_file("dir/note.txt") == "hi"
    sandbox.script(CommandResult(command="", exit_code=3, stderr="nope"))
    result = sandbox.run("echo hi", timeout=1.5)
    assert result.exit_code == 3
    assert result.command == "echo hi"
    assert sandbox.commands == ["echo hi"]
    assert sandbox.timeouts == [1.5]
    with pytest.raises(SandboxError):
        sandbox.read_file("../outside.txt")


def test_memory_store_add_search_get_delete() -> None:
    store = InMemoryMemoryStore()
    first = store.add("Alpha note", metadata={"tag": "docs"})
    second = store.add("beta ALPHA", metadata={"tag": "other"})
    assert store.get(first.id) == first
    assert store.get("missing") is None
    found = store.search("alpha")
    assert [item.id for item in found] == [second.id, first.id]
    assert store.search("docs")[0].id == first.id
    assert store.search("   ") == []
    assert store.delete(first.id) is True
    assert store.delete(first.id) is False
    assert store.get(first.id) is None


def test_auto_approve_records_prompt() -> None:
    prompter = AutoApprovePrompter()
    action = ActionRequest(kind=ActionKind.READ_FILE.value, summary="read a", risk=RiskLevel.READ)
    assert prompter.prompt(action) is True
    assert prompter.prompts == [action]


def test_registry_call_and_missing() -> None:
    registry = InMemoryToolRegistry()
    registry.register(
        Tool(name="add", description="add two numbers"),
        lambda a, b: {"sum": a + b},
    )
    text = registry.call(ToolCall(id="1", name="add", arguments={"a": 1, "b": 2}))
    assert text == '{"sum": 3}'
    with pytest.raises(KeyError):
        registry.get("missing")


def test_factories_are_stubs_and_loop_returns_a_plan(tmp_path: Path) -> None:
    from swag_bot.config import Settings

    settings = Settings()
    for factory in (
        build_llm_client,
        build_memory_store,
    ):
        with pytest.raises(NotImplementedYet):
            factory(settings)
    sandbox = build_sandbox(settings)
    assert sandbox.workdir.is_dir()
    policy = build_permission_policy(settings)
    assert policy.autonomy is AutonomyLevel.ASK_RISKY
    prompter = build_prompter(settings)
    assert callable(prompter.prompt)
    client = build_mcp_client(settings)
    assert client.list_tools() == []
    client.close()
    client.close()

    class _Policy:
        @property
        def autonomy(self) -> AutonomyLevel:
            return AutonomyLevel.AUTO

        def classify(self, action: ActionRequest) -> RiskLevel:
            return action.risk

        def requires_approval(self, action: ActionRequest) -> bool:
            return default_requires_approval(self.autonomy, action.risk)

    policy: PermissionPolicy = _Policy()
    loop = PlanDoVerifyLoop(
        llm=FakeLLMClient(),
        sandbox=FakeSandbox(tmp_path / "work"),
        memory=InMemoryMemoryStore(),
        policy=policy,
        prompter=AutoApprovePrompter(),
    )
    plan = loop.run("do the thing")
    assert plan.goal == "do the thing"
    assert plan.steps
    assert plan.steps[0].status in {StepStatus.DONE, StepStatus.FAILED}
