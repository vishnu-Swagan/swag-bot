"""Tab-tool risks match the headless browser plugin, and approvals still apply."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from swag_bot.core.executor import StepExecutor
from swag_bot.extension.policy import TAB_RISK, CatalogRiskPolicy, approval_view
from swag_bot.extension.tab_tools import (
    TabDispatcher,
    format_tab_result,
    register_chrome_tab_tools,
    validate_tab_arguments,
)
from swag_bot.interfaces import (
    ActionRequest,
    AutonomyLevel,
    ChatResponse,
    Message,
    RiskLevel,
    Step,
    ToolCall,
)
from swag_bot.registry import InMemoryToolRegistry
from swag_bot.safety.policy import DefaultPermissionPolicy, PolicyDecision
from tests.fakes import FakeLLMClient, InMemoryMemoryStore


class RecordingPrompter:
    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.actions: list[ActionRequest] = []

    def prompt(self, action: ActionRequest) -> bool:
        self.actions.append(action)
        return self.allow


class ImmediateBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def request(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float | None,
    ) -> Mapping[str, Any]:
        del timeout
        tool = str(payload["tool"])
        arguments = payload["arguments"]
        assert isinstance(arguments, dict)
        self.calls.append((tool, arguments))
        return {
            "ok": True,
            "title": "Example",
            "url": "https://example.com/",
            "content": "Hello from the page",
            "detail": arguments.get("selector", ""),
        }


def _executor(
    responses: list[ChatResponse | str],
    *,
    autonomy: AutonomyLevel,
    allow: bool,
    grants: dict[str, set[str]] | None = None,
) -> tuple[StepExecutor, RecordingPrompter, ImmediateBridge]:
    bridge = ImmediateBridge()
    registry = InMemoryToolRegistry()
    register_chrome_tab_tools(registry, TabDispatcher(bridge, run_id="run-1"))
    prompter = RecordingPrompter(allow)
    policy = CatalogRiskPolicy(DefaultPermissionPolicy(autonomy, grants=grants or {}, workdir=None))
    executor = StepExecutor(
        llm=FakeLLMClient(responses),
        tools=registry,
        policy=policy,
        prompter=prompter,
        memory=InMemoryMemoryStore(),
        max_tool_rounds=4,
    )
    return executor, prompter, bridge


def _call(name: str, arguments: dict[str, Any]) -> ChatResponse:
    return ChatResponse(
        message=Message.assistant(tool_calls=[ToolCall(id="c1", name=name, arguments=arguments)])
    )


def test_catalog_risks_match_the_browser_plugin() -> None:
    assert TAB_RISK == {
        "browser__snapshot": RiskLevel.READ,
        "browser__extract": RiskLevel.READ,
        "browser__type_text": RiskLevel.WRITE,
        "browser__fill": RiskLevel.WRITE,
        "browser__click": RiskLevel.EXECUTE,
        "browser__navigate": RiskLevel.NETWORK,
        "browser__submit": RiskLevel.NETWORK,
    }


def test_snapshot_does_not_prompt_at_ask_risky() -> None:
    executor, prompter, bridge = _executor(
        [_call("browser__snapshot", {}), "the page says hello"],
        autonomy=AutonomyLevel.ASK_RISKY,
        allow=False,
    )
    result = executor.execute(Step(id="s1", title="Read the page"), attempt=1, feedback=None)
    assert prompter.actions == []
    assert bridge.calls == [("browser__snapshot", {})]
    assert "hello" in result.observation


def test_snapshot_prompts_at_ask_always() -> None:
    executor, prompter, bridge = _executor(
        [_call("browser__snapshot", {}), "read"],
        autonomy=AutonomyLevel.ASK_ALWAYS,
        allow=True,
    )
    executor.execute(Step(id="s1", title="Read the page"), attempt=1, feedback=None)
    assert len(prompter.actions) == 1
    assert prompter.actions[0].risk is RiskLevel.READ
    assert bridge.calls


def test_denied_click_does_not_reach_the_tab() -> None:
    executor, prompter, bridge = _executor(
        [_call("browser__click", {"selector": "#go"}), "denied"],
        autonomy=AutonomyLevel.ASK_RISKY,
        allow=False,
    )
    executor.execute(Step(id="s1", title="Click go"), attempt=1, feedback=None)
    assert prompter.actions[0].risk is RiskLevel.EXECUTE
    assert bridge.calls == []


def test_navigate_prompts_as_network_and_shows_the_url() -> None:
    executor, prompter, bridge = _executor(
        [
            _call("browser__navigate", {"url": "https://example.com/docs"}),
            "opened the docs",
        ],
        autonomy=AutonomyLevel.ASK_RISKY,
        allow=True,
    )
    executor.execute(Step(id="s1", title="Open the docs"), attempt=1, feedback=None)
    action = prompter.actions[0]
    assert action.risk is RiskLevel.NETWORK
    view = approval_view(action)
    assert "https://example.com/docs" in view["summary"]
    assert bridge.calls[0][0] == "browser__navigate"


def test_missing_plugin_grant_is_a_hard_deny() -> None:
    policy = CatalogRiskPolicy(DefaultPermissionPolicy(AutonomyLevel.AUTO, grants={}, workdir=None))
    action = ActionRequest(
        kind="tool",
        summary="browser__click",
        risk=RiskLevel.EXECUTE,
        arguments={"plugin": "browser", "selector": "#a"},
    )
    assert policy.decide(action) is PolicyDecision.DENY
    executor, prompter, bridge = _executor(
        [_call("browser__click", {"selector": "#a", "plugin": "browser"}), "nope"],
        autonomy=AutonomyLevel.AUTO,
        allow=True,
    )
    executor.execute(Step(id="s1", title="Click"), attempt=1, feedback=None)
    assert prompter.actions == []
    assert bridge.calls == []


def test_destructive_snapshot_is_not_lowered() -> None:
    policy = CatalogRiskPolicy(
        DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY, grants={}, workdir=None)
    )
    action = ActionRequest(
        kind="delete",
        summary="browser__snapshot",
        risk=RiskLevel.DESTRUCTIVE,
    )
    assert policy.classify(action) is RiskLevel.DESTRUCTIVE
    assert policy.requires_approval(action) is True


def test_url_and_selector_validation() -> None:
    assert validate_tab_arguments("browser__navigate", {"url": "https://example.com"}) == {
        "url": "https://example.com"
    }
    for bad in (
        "javascript:alert(1)",
        "file:///tmp/x",
        "data:text/html,hi",
        "https://user:pw@host",
    ):
        try:
            validate_tab_arguments("browser__navigate", {"url": bad})
        except ValueError:
            continue
        raise AssertionError(bad)
    try:
        validate_tab_arguments("browser__click", {"selector": ""})
    except ValueError:
        pass
    else:
        raise AssertionError("empty selector")


def test_format_refuses_a_failed_tab_action() -> None:
    text = format_tab_result("browser__click", {"ok": False, "error": "No element matches #gone"})
    assert text.startswith("error:")
    assert "gone" in text
