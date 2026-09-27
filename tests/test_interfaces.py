"""The shared contracts import, validate, and accept structural implementations."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from swag_bot.errors import SandboxError
from swag_bot.interfaces import (
    TIMEOUT_EXIT_CODE,
    ActionRequest,
    AgentLoop,
    ApprovalPrompter,
    AutonomyLevel,
    LLMClient,
    MCPClient,
    MemoryStore,
    Message,
    Permission,
    PermissionPolicy,
    Plugin,
    PluginManifest,
    RiskLevel,
    Role,
    Sandbox,
    Skill,
    SkillMeta,
    Step,
    StepStatus,
    TaskPlan,
    ToolCall,
    ToolRegistry,
    default_requires_approval,
    resolve_sandbox_path,
)
from swag_bot.registry import InMemoryToolRegistry
from tests.fakes import AutoApprovePrompter, FakeLLMClient, FakeSandbox, InMemoryMemoryStore


def test_public_names_import() -> None:
    from swag_bot import interfaces

    for name in (
        "LLMClient",
        "Message",
        "ToolCall",
        "Tool",
        "ToolRegistry",
        "SkillMeta",
        "Skill",
        "PluginManifest",
        "Plugin",
        "PermissionPolicy",
        "ApprovalPrompter",
        "Sandbox",
        "MemoryStore",
        "TaskPlan",
        "Step",
        "StepResult",
        "StepStatus",
        "ActionLogEntry",
    ):
        assert hasattr(interfaces, name)


def test_tool_call_parses_json_arguments() -> None:
    call = ToolCall(id="1", name="read", arguments='{"path": "a.txt"}')  # type: ignore[arg-type]
    assert call.arguments == {"path": "a.txt"}


def test_message_helpers() -> None:
    assert Message.user("hi").role is Role.USER
    result = Message.tool("1", "ok")
    assert result.role is Role.TOOL
    assert result.tool_call_id == "1"


def test_skill_meta_rules() -> None:
    meta = SkillMeta.model_validate(
        {
            "name": "pdf-processing",
            "description": "Extract text from PDFs. Use when the user mentions PDFs.",
            "allowed-tools": "Read Bash",
        }
    )
    assert meta.allowed_tools == "Read Bash"
    with pytest.raises(ValidationError):
        SkillMeta(name="Bad_Name", description="nope")
    with pytest.raises(ValidationError):
        SkillMeta(name="ok", description="")


def test_plugin_manifest_roundtrip() -> None:
    raw = {
        "name": "deployment-tools",
        "displayName": "Deployment Tools",
        "version": "1.2.0",
        "description": "Brief plugin description",
        "author": {"name": "Author Name", "email": "author@example.com"},
        "skills": "./custom/skills/",
        "commands": ["./custom/commands/special.md"],
        "mcpServers": "./mcp-config.json",
        "dependencies": ["helper-lib", {"name": "secrets-vault", "version": "~2.1.0"}],
        "permissions": [Permission.FILESYSTEM_READ.value, Permission.SHELL.value],
        "futureField": {"kept": True},
    }
    manifest = PluginManifest.from_plugin_json(raw)
    assert manifest.display_name == "Deployment Tools"
    assert manifest.permissions == ["filesystem.read", "shell"]
    assert manifest.dependencies[0].name == "helper-lib"
    assert manifest.dependencies[1].version == "~2.1.0"
    again = PluginManifest.from_plugin_json(manifest.to_plugin_json())
    assert again.name == manifest.name
    assert again.mcp_servers == "./mcp-config.json"
    assert again.permissions == manifest.permissions
    assert again.model_extra is not None
    assert again.model_extra["futureField"] == {"kept": True}


def test_plugin_manifest_string_author() -> None:
    manifest = PluginManifest.from_plugin_json({"name": "demo", "author": "Ada"})
    assert manifest.author is not None
    assert manifest.author.name == "Ada"


def test_task_plan_rejects_bad_steps() -> None:
    with pytest.raises(ValidationError):
        TaskPlan(
            goal="ship it",
            steps=[
                Step(id="a", title="one"),
                Step(id="a", title="two"),
            ],
        )
    with pytest.raises(ValidationError):
        TaskPlan(goal="ship it", steps=[Step(id="a", title="one", depends_on=["missing"])])
    plan = TaskPlan(goal="ship it")
    assert plan.steps == []
    assert plan.id


@pytest.mark.parametrize(
    ("autonomy", "risk", "expected"),
    [
        (AutonomyLevel.ASK_ALWAYS, RiskLevel.READ, True),
        (AutonomyLevel.ASK_ALWAYS, RiskLevel.DESTRUCTIVE, True),
        (AutonomyLevel.ASK_RISKY, RiskLevel.READ, False),
        (AutonomyLevel.ASK_RISKY, RiskLevel.WRITE, True),
        (AutonomyLevel.ASK_RISKY, RiskLevel.EXECUTE, True),
        (AutonomyLevel.ASK_RISKY, RiskLevel.NETWORK, True),
        (AutonomyLevel.ASK_RISKY, RiskLevel.DESTRUCTIVE, True),
        (AutonomyLevel.AUTO, RiskLevel.READ, False),
        (AutonomyLevel.AUTO, RiskLevel.DESTRUCTIVE, False),
    ],
)
def test_approval_matrix(autonomy: AutonomyLevel, risk: RiskLevel, expected: bool) -> None:
    assert default_requires_approval(autonomy, risk) is expected


def test_timeout_exit_code() -> None:
    assert TIMEOUT_EXIT_CODE == 124


def test_resolve_sandbox_path(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    inside = resolve_sandbox_path(work, "notes/a.txt")
    assert inside == (work / "notes" / "a.txt").resolve()
    with pytest.raises(SandboxError):
        resolve_sandbox_path(work, "../secret")
    with pytest.raises(SandboxError):
        resolve_sandbox_path(work, str(tmp_path / "secret"))
    outside = tmp_path / "secret"
    outside.write_text("nope", encoding="utf-8")
    link = work / "link"
    link.symlink_to(outside)
    with pytest.raises(SandboxError):
        resolve_sandbox_path(work, "link")


def test_protocols_accept_fakes(tmp_path: Path) -> None:
    assert isinstance(FakeLLMClient(), LLMClient)
    assert isinstance(FakeSandbox(tmp_path / "box"), Sandbox)
    assert isinstance(InMemoryMemoryStore(), MemoryStore)
    assert isinstance(AutoApprovePrompter(), ApprovalPrompter)
    assert isinstance(InMemoryToolRegistry(), ToolRegistry)


def test_skill_and_plugin_protocols(tmp_path: Path) -> None:
    meta = SkillMeta(name="demo-skill", description="A demo skill used by the smoke test.")

    class _Skill:
        @property
        def meta(self) -> SkillMeta:
            return meta

        def instructions(self) -> str:
            return "Do the demo."

        def resources(self) -> list[str]:
            return []

        def read_resource(self, relative_path: str) -> str:
            raise FileNotFoundError(relative_path)

    class _Plugin:
        @property
        def manifest(self) -> PluginManifest:
            return PluginManifest(name="demo")

        @property
        def root(self) -> Path:
            return tmp_path

        def list_skills(self) -> list[SkillMeta]:
            return [meta]

        def load_skill(self, name: str) -> _Skill:
            if name != meta.name:
                raise KeyError(name)
            return _Skill()

        def list_commands(self) -> list[object]:
            return []

    assert isinstance(_Skill(), Skill)
    assert isinstance(_Plugin(), Plugin)


def test_policy_and_mcp_and_loop_shapes() -> None:
    class _Policy:
        @property
        def autonomy(self) -> AutonomyLevel:
            return AutonomyLevel.ASK_RISKY

        def classify(self, action: ActionRequest) -> RiskLevel:
            return action.risk

        def requires_approval(self, action: ActionRequest) -> bool:
            return default_requires_approval(self.autonomy, self.classify(action))

    class _MCP:
        def list_tools(self) -> list[object]:
            return []

        def call_tool(self, name: str, arguments: dict[str, object]) -> str:
            raise KeyError(name)

        def close(self) -> None:
            return None

    class _Loop:
        def run(self, goal: str) -> TaskPlan:
            return TaskPlan(goal=goal)

    assert isinstance(_Policy(), PermissionPolicy)
    assert isinstance(_MCP(), MCPClient)
    assert isinstance(_Loop(), AgentLoop)


def test_step_status_values() -> None:
    assert StepStatus.DONE.value == "done"
    assert StepStatus.VERIFYING.value == "verifying"
