"""Browser tools go through the executor and the permission policy."""

from __future__ import annotations

from swag_bot.browser.catalog import TOOLS
from swag_bot.core.executor import StepExecutor
from swag_bot.interfaces import (
    ActionLogEntry,
    AutonomyLevel,
    ChatResponse,
    Message,
    Step,
    ToolCall,
)
from swag_bot.registry import InMemoryToolRegistry
from swag_bot.safety.policy import DefaultPermissionPolicy
from tests.fakes import AutoApprovePrompter, FakeLLMClient, InMemoryMemoryStore


def _registry() -> tuple[InMemoryToolRegistry, list[str]]:
    registry = InMemoryToolRegistry()
    calls: list[str] = []

    def handler(**_arguments: object) -> str:
        calls.append("called")
        return "ok"

    for spec in TOOLS.values():
        registry.register(spec.as_tool(), handler)
    return registry, calls


def _executor(
    registry: InMemoryToolRegistry,
    responses: list[ChatResponse],
    *,
    grants: dict[str, set[str]],
    autonomy: AutonomyLevel = AutonomyLevel.ASK_RISKY,
) -> tuple[StepExecutor, AutoApprovePrompter, list[ActionLogEntry]]:
    prompter = AutoApprovePrompter()
    log: list[ActionLogEntry] = []
    executor = StepExecutor(
        llm=FakeLLMClient(responses),
        tools=registry,
        policy=DefaultPermissionPolicy(autonomy, grants=grants),
        prompter=prompter,
        memory=InMemoryMemoryStore(),
        on_action=log.append,
    )
    return executor, prompter, log


def _turn(name: str, arguments: dict[str, str], observation: str) -> list[ChatResponse]:
    return [
        ChatResponse(
            message=Message.assistant(
                tool_calls=[ToolCall(id="1", name=name, arguments=arguments)]
            )
        ),
        ChatResponse(message=Message.assistant(observation)),
    ]


def test_snapshot_is_allowed_and_navigate_prompts() -> None:
    registry, calls = _registry()
    grants = {"browser": {"network", "mcp", "filesystem.write"}}
    executor, prompter, log = _executor(
        registry,
        _turn("browser__snapshot", {}, "the heading is Example Domain"),
        grants=grants,
    )
    result = executor.execute(Step(id="read", title="Read the page"), attempt=1, feedback=None)
    assert "Example Domain" in result.observation
    assert prompter.prompts == []
    assert calls == ["called"]
    assert log[0].approved is True
    assert log[0].approver == "policy"
    assert log[0].action.risk.value == "read"

    calls.clear()
    executor, prompter, log = _executor(
        registry,
        _turn("browser__navigate", {"url": "https://example.com"}, "opened"),
        grants=grants,
    )
    executor.execute(Step(id="open", title="Open the page"), attempt=1, feedback=None)
    assert len(prompter.prompts) == 1
    prompt = prompter.prompts[0]
    assert prompt.arguments["plugin"] == "browser"
    assert prompt.arguments["permission"] == "network"
    assert "https://example.com" in prompt.summary
    assert prompt.risk.value == "network"
    assert calls == ["called"]


def test_missing_network_grant_denies_navigate_without_a_prompt() -> None:
    registry, calls = _registry()
    executor, prompter, log = _executor(
        registry,
        _turn("browser__navigate", {"url": "https://example.com"}, "should not run"),
        grants={"browser": {"mcp"}},
        autonomy=AutonomyLevel.AUTO,
    )
    executor.execute(Step(id="open", title="Open the page"), attempt=1, feedback=None)
    assert calls == []
    assert prompter.prompts == []
    assert log[0].approved is False
    assert log[0].approver == "policy"


def test_model_cannot_relabel_a_navigate_as_a_read() -> None:
    registry, calls = _registry()
    executor, prompter, _log = _executor(
        registry,
        _turn(
            "browser__navigate",
            {
                "url": "https://example.com",
                "risk_hint": "read",
                "permission": "mcp",
                "plugin": "other",
            },
            "opened",
        ),
        grants={"browser": {"network", "mcp", "filesystem.write"}},
    )
    executor.execute(Step(id="open", title="Open the page"), attempt=1, feedback=None)
    assert len(prompter.prompts) == 1
    prompt = prompter.prompts[0]
    assert prompt.arguments["plugin"] == "browser"
    assert prompt.arguments["permission"] == "network"
    assert prompt.arguments["risk_hint"] == "network"
    assert calls == ["called"]


def test_screenshot_needs_the_write_grant() -> None:
    registry, calls = _registry()
    executor, prompter, log = _executor(
        registry,
        _turn("browser__screenshot", {"path": "page.png"}, "saved"),
        grants={"browser": {"network", "mcp"}},
        autonomy=AutonomyLevel.AUTO,
    )
    executor.execute(Step(id="shot", title="Save a screenshot"), attempt=1, feedback=None)
    assert calls == []
    assert prompter.prompts == []
    assert log[0].approved is False
