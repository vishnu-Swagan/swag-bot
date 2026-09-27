"""Shared contracts for Swag Bot.

Every owned package codes against this module. The shapes here are stable:

- Add fields only with defaults.
- Add protocols, enum members, and functions. Do not rename or remove them.
- Do not tighten a type in a way that rejects values older code already emits.
- Do not import ``config``, ``cli``, or any owned package from this module.
  Those packages import this one.

Data is pydantic models. Behavior is ``Protocol``s (``@runtime_checkable`` so
tests and fakes can use ``isinstance``). A protocol method that a particular
backend cannot support should raise ``NotImplementedError`` rather than
silently no-op, unless the docstring says otherwise.

Streaming is optional: implement ``StreamingLLMClient`` only when the
provider can actually stream. ``LLMClient`` alone is enough for the loop.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from swag_bot.errors import SandboxError

# GNU timeout's conventional status. Sandbox implementations use this when a
# command exceeds ``timeout`` so callers do not have to catch a special error.
TIMEOUT_EXIT_CODE = 124

# Evidence Contract. The prose spec is ``docs/spec/evidence-contract.md``.
# Skill learning, replay, and jury features should read that file and these
# models rather than inventing a second ledger shape.
EVIDENCE_CONTRACT_SPEC = "swag-evidence-contract"
EVIDENCE_CONTRACT_VERSION = "1.0"

_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Chat model
# ---------------------------------------------------------------------------


class Role(StrEnum):
    """Message role on the wire. Values match the usual chat JSON."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """One tool invocation requested by the model.

    ``arguments`` is a JSON object. If a provider returns a JSON string, the
    validator parses it. Callers always see a dict.
    """

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments", mode="before")
    @classmethod
    def _parse_arguments(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip() or "{}"
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                raise ValueError("tool call arguments must be a JSON object")
            return loaded
        return value


class Message(BaseModel):
    """One turn in a chat.

    ``content`` may be null when an assistant message is only tool calls.
    Tool results use ``role=tool``, ``tool_call_id``, and string ``content``.
    Multimodal parts are out of scope; add a new field if they are needed.
    """

    role: Role
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(
        cls,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
    ) -> Message:
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool(cls, tool_call_id: str, content: str) -> Message:
        return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id)


class Tool(BaseModel):
    """A tool the model may call. ``parameters`` is a JSON Schema object.

    ``annotations`` is an open bag for tool metadata. Swag Bot reads
    ``swagCompensation`` from it when an MCP tool declares an inverse.
    ``risk_hint``, ``permission_hint``, and ``plugin`` are optional metadata
    for the permission policy. They are not sent to the model. The executor
    copies them onto the action and ignores any copy the model puts in the
    tool arguments. Hints never lower a ``destructive`` classification.
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    annotations: dict[str, Any] = Field(default_factory=dict)
    risk_hint: str | None = None
    permission_hint: str | None = None
    plugin: str | None = None


class ChatResponse(BaseModel):
    """A completed non-streaming model turn."""

    message: Message
    model: str | None = None
    finish_reason: str | None = None


class ChatChunk(BaseModel):
    """One incremental piece of a streaming turn.

    ``tool_call_deltas`` carries partial tool calls as the provider emits
    them. The caller assembles the final ``ToolCall`` list. A chunk with
    ``finish_reason`` set is the last chunk.
    """

    delta: str = ""
    tool_call_deltas: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    """Chat and single-shot completion.

    Implementations live in ``swag_bot.models``. API keys come from the
    environment, never from arguments that would end up in a log.
    """

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        """Return the next assistant message, including any tool calls."""
        ...

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        """Single-turn completion. May delegate to ``chat``."""
        ...


@runtime_checkable
class StreamingLLMClient(LLMClient, Protocol):
    """``LLMClient`` that can also stream. Do not claim this if you buffer."""

    def stream(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
    ) -> Iterator[ChatChunk]:
        """Yield assistant output as it arrives."""
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Named tools and the Python callables behind them.

    ``InMemoryToolRegistry`` in ``swag_bot.registry`` is the default.
    ``list_tools`` is the method name (``list`` would shadow the builtin).
    """

    def register(self, tool: Tool, handler: Callable[..., Any]) -> None:
        """Replace any previous tool with the same name."""
        ...

    def get(self, name: str) -> Tool:
        """Return the tool spec. Raise ``KeyError`` if it is missing."""
        ...

    def list_tools(self) -> Sequence[Tool]:
        """Return every registered tool spec."""
        ...

    def call(self, tool_call: ToolCall) -> str:
        """Run the handler and return text for a tool-result message.

        Handlers return ``str`` or a JSON-serializable value. Missing tools
        raise ``KeyError``.
        """
        ...


# ---------------------------------------------------------------------------
# Agent Skills and Cowork / Claude Code plugins
# ---------------------------------------------------------------------------


class SkillMeta(BaseModel):
    """Level-1 skill metadata. Loaded for every skill at startup.

    Mirrors the Agent Skills frontmatter (https://agentskills.io/specification):
    ``name`` and ``description`` are required. ``location`` is Swag Bot's
    pointer at the skill directory and is not part of the frontmatter file.

    The plugins agent parses YAML and calls ``model_validate``. This package
    does not depend on a YAML library. The parent directory name must equal
    ``name``; the loader checks that, not this model.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    allowed_tools: str | None = Field(default=None, alias="allowed-tools")
    location: Path | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not 1 <= len(value) <= 64 or _SKILL_NAME.fullmatch(value) is None:
            raise ValueError(
                "skill name must be 1-64 characters of lowercase letters, digits, "
                "and single hyphens, and must not start or end with a hyphen"
            )
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        if not value.strip() or len(value) > 1024:
            raise ValueError("description must be 1-1024 non-empty characters")
        return value

    @field_validator("compatibility")
    @classmethod
    def _compatibility(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 500:
            raise ValueError("compatibility must be at most 500 characters")
        return value


@runtime_checkable
class Skill(Protocol):
    """A skill loaded in three steps (progressive disclosure).

    1. ``meta`` is name + description, available before the body is read.
    2. ``instructions()`` is the ``SKILL.md`` markdown body, frontmatter removed.
    3. ``resources()`` lists files; ``read_resource()`` reads one of them
       (typically under ``scripts/``, ``references/``, or ``assets/``).
    """

    @property
    def meta(self) -> SkillMeta:
        """Discovery metadata. Must not require reading the body."""
        ...

    def instructions(self) -> str:
        """Return the ``SKILL.md`` body."""
        ...

    def resources(self) -> Sequence[str]:
        """Relative paths of bundled files. Do not read their contents here."""
        ...

    def read_resource(self, relative_path: str) -> str:
        """Return one bundled file as text. Raise ``FileNotFoundError`` if missing."""
        ...


class SlashCommand(BaseModel):
    """A Claude Code style slash command (``commands/*.md``).

    ``body`` stays empty until the command is invoked, same idea as skills:
    the description is for discovery, the body is the prompt.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    description: str = ""
    body: str = ""
    argument_hint: str | None = Field(default=None, alias="argument-hint")
    allowed_tools: str | None = Field(default=None, alias="allowed-tools")


class AgentDefinition(BaseModel):
    """A sub-agent from a plugin ``agents/*.md`` file.

    ``body`` stays empty until the agent is invoked, same as ``SlashCommand``.
    ``tools`` is the frontmatter tool list (a space-separated string). ``model``
    is the requested model, or None to inherit the session model.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    description: str = ""
    body: str = ""
    tools: str | None = None
    model: str | None = None


class Permission(StrEnum):
    """Built-in plugin capability names.

    ``PluginManifest.permissions`` is an open ``list[str]``. Use these values
    for the common cases. Custom capabilities should be dotted names such as
    ``com.example.deploy``. Unknown names are treated as risky by policy.
    """

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    SHELL = "shell"
    NETWORK = "network"
    MCP = "mcp"
    SECRETS = "secrets"


class PluginAuthor(BaseModel):
    """``author`` object from ``plugin.json``."""

    model_config = ConfigDict(extra="allow")

    name: str
    email: str | None = None
    url: str | None = None


class PluginDependency(BaseModel):
    """One entry from ``dependencies``. A bare string in JSON becomes a name."""

    model_config = ConfigDict(extra="allow")

    name: str
    version: str | None = None


class UserConfigOption(BaseModel):
    """One ``userConfig`` field. Known types: string, number, boolean, directory, file."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str = ""
    description: str = ""
    sensitive: bool = False
    required: bool = False
    default: Any = None
    multiple: bool = False
    min: float | None = None
    max: float | None = None


class PluginChannel(BaseModel):
    """A ``channels`` entry. ``server`` matches a key in ``mcpServers``."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    server: str
    user_config: dict[str, UserConfigOption] | None = Field(default=None, alias="userConfig")


class ExperimentalComponents(BaseModel):
    """``experimental`` block. ``themes`` and ``monitors`` are path specs."""

    model_config = ConfigDict(extra="allow")

    themes: str | list[str] | None = None
    monitors: str | list[str] | None = None


class PluginManifest(BaseModel):
    """``.claude-plugin/plugin.json``, plus Swag Bot's ``permissions`` list.

    Field names match the Claude Code / Cowork manifest. Claude Code ignores
    unknown top-level fields, so ``permissions`` can live in the same file
    and still load there. Component paths are relative to the plugin root
    and, when they are paths, start with ``./``.

    ``skills``, ``commands``, ``agents``, ``outputStyles``, and ``workflows``
    are a path or a list of paths. ``hooks``, ``mcpServers``, and ``lspServers``
    may instead be an inline JSON object. Extra keys are preserved.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    display_name: str | None = Field(default=None, alias="displayName")
    version: str | None = None
    description: str | None = None
    author: PluginAuthor | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: list[str] = Field(default_factory=list)
    default_enabled: bool = Field(default=True, alias="defaultEnabled")
    skills: str | list[str] | None = None
    commands: str | list[str] | None = None
    agents: str | list[str] | None = None
    workflows: str | list[str] | None = None
    hooks: str | list[Any] | dict[str, Any] | None = None
    mcp_servers: str | list[Any] | dict[str, Any] | None = Field(default=None, alias="mcpServers")
    output_styles: str | list[str] | None = Field(default=None, alias="outputStyles")
    lsp_servers: str | list[Any] | dict[str, Any] | None = Field(default=None, alias="lspServers")
    user_config: dict[str, UserConfigOption] = Field(default_factory=dict, alias="userConfig")
    channels: list[PluginChannel] = Field(default_factory=list)
    experimental: ExperimentalComponents | None = None
    dependencies: list[PluginDependency] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    compensations: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value or len(value) > 64 or any(ch.isspace() or ch in "/\\" for ch in value):
            raise ValueError("plugin name must be 1-64 characters and must not contain spaces")
        return value

    @field_validator("author", mode="before")
    @classmethod
    def _author(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @field_validator("dependencies", mode="before")
    @classmethod
    def _dependencies(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("dependencies must be a list")
        normalized: list[Any] = []
        for item in value:
            if isinstance(item, str):
                normalized.append({"name": item})
            else:
                normalized.append(item)
        return normalized

    @field_validator("permissions")
    @classmethod
    def _permissions(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or not item or any(ch.isspace() for ch in item):
                raise ValueError("permission names must be non-empty and contain no whitespace")
        return value

    @field_validator("compensations", mode="before")
    @classmethod
    def _compensations(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("compensations must be a list of objects")
        return value

    @classmethod
    def from_plugin_json(cls, data: Mapping[str, Any]) -> PluginManifest:
        """Validate a decoded ``plugin.json`` object."""
        return cls.model_validate(dict(data))

    def to_plugin_json(self) -> dict[str, Any]:
        """Dict shaped like ``plugin.json`` (camelCase aliases, no nulls)."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


@runtime_checkable
class Plugin(Protocol):
    """A loaded Cowork / Claude Code compatible plugin directory."""

    @property
    def manifest(self) -> PluginManifest:
        """Parsed ``.claude-plugin/plugin.json``, or a synthetic one from the directory name."""
        ...

    @property
    def root(self) -> Path:
        """Plugin root. Component paths resolve under this directory."""
        ...

    def list_skills(self) -> Sequence[SkillMeta]:
        """Level-1 metadata only. Do not read ``SKILL.md`` bodies here."""
        ...

    def load_skill(self, name: str) -> Skill:
        """Return one skill. Raise ``KeyError`` if ``name`` is not in the plugin."""
        ...

    def list_commands(self) -> Sequence[SlashCommand]:
        """Slash commands. Bodies may be empty until a command is invoked."""
        ...


# ---------------------------------------------------------------------------
# Permissions, approval, sandbox, action log
# ---------------------------------------------------------------------------


class AutonomyLevel(StrEnum):
    """How often the agent asks before acting.

    - ``ask-always``: prompt for every action, including reads.
    - ``ask-risky``: prompt for anything that is not a pure read. This is
      the default.
    - ``ask-irreversible``: prompt only at the point of no return
      (``Reversibility.IRREVERSIBLE``). Reversible workspace edits, including
      shell changes inside the snapshotted workdir, and compensable actions
      proceed without a prompt. This is a separate mode. It does not weaken
      ``ask-risky``.
    - ``auto``: do not prompt. Still log every action. A policy may still
      hard-deny; skipping the prompt is not the same as allowing everything.
    """

    ASK_ALWAYS = "ask-always"
    ASK_RISKY = "ask-risky"
    ASK_IRREVERSIBLE = "ask-irreversible"
    AUTO = "auto"


class RiskLevel(StrEnum):
    """How dangerous an action is.

    - ``read``: no side effects.
    - ``write``: local mutation that can be reviewed.
    - ``execute``: run a command or code.
    - ``network``: any outbound connection.
    - ``destructive``: delete, overwrite secrets, or anything hard to undo.
    """

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    DESTRUCTIVE = "destructive"


class Reversibility(StrEnum):
    """Whether an action can be rolled back after it runs.

    Risk and reversibility are different. A shell ``rm`` inside the sandbox
    workdir is destructive and still reversible, because a snapshot was taken
    first. Sending email is irreversible even when the risk is only ``network``.

    - ``reversible``: workspace files, including changes a shell command makes
      inside the snapshotted workdir.
    - ``compensable``: an external side effect with a registered inverse, such
      as closing an issue the tool just created.
    - ``irreversible``: a point of no return. Undo cannot restore it.
    """

    REVERSIBLE = "reversible"
    COMPENSABLE = "compensable"
    IRREVERSIBLE = "irreversible"


class ActionKind(StrEnum):
    """Suggested ``ActionRequest.kind`` values. The field itself is open."""

    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    RUN_COMMAND = "run_command"
    NETWORK = "network"
    TOOL = "tool"
    MEMORY = "memory"
    DELETE = "delete"


class ActionRequest(BaseModel):
    """Something the agent wants to do, before it happens.

    Callers redact secrets before building this. The action log stores it.
    """

    kind: str
    summary: str
    risk: RiskLevel
    target: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reversibility: Reversibility | None = None
    tool_name: str | None = None


# Key on ``ActionRequest.arguments`` written by a ``TaintTracker``. Tool
# arguments that use the same name are stripped before the policy reads it.
SWAG_TAINT_KEY = "_swag_taint"


class TrustLevel(StrEnum):
    """Whether a span of data may choose a sensitive action by itself.

    ``trusted`` is the user goal and other data the user marked trusted.
    ``untrusted`` is data the agent read from outside that trust boundary
    (web pages, MCP results, plugin output, files outside the workspace).
    """

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


@runtime_checkable
class TaintTracker(Protocol):
    """Labels data by source and trust, and quarantines untrusted tool output.

    This is span- and argument-level tracking, not a proof of information
    flow. ``prepare`` may raise ``action.risk`` and attach a ``_swag_taint``
    stamp. It must not lower a ``destructive`` risk. ``label_output`` returns
    the text the model is allowed to see. ``observe_result`` records a result
    the caller will return raw (the executor quarantines it later).
    """

    def note(self, text: str, *, source: str, trust: TrustLevel) -> None:
        """Record text that entered the agent, such as the user goal."""
        ...

    def register_tool(self, name: str, meta: Mapping[str, Any]) -> None:
        """Record MCP ``_meta.swag`` (risk, sinks, source).

        Metadata may raise risk or name a source. It must not be able to mark
        MCP or web output as trusted.
        """
        ...

    def prepare(self, action: ActionRequest, *, tool: str) -> ActionRequest:
        """Stamp ``action`` before the permission policy sees it."""
        ...

    def label_output(self, tool: str, arguments: Mapping[str, Any], output: str) -> str:
        """Record tool output and return the model-facing text."""
        ...

    def observe_result(
        self,
        tool: str,
        output: str,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a tool result without changing the text returned to the caller."""
        ...


def default_requires_approval(
    autonomy: AutonomyLevel,
    risk: RiskLevel,
    *,
    reversibility: Reversibility | None = None,
) -> bool:
    """Whether ``autonomy`` should prompt before an action of ``risk``.

    ``ask-always`` prompts every time. ``ask-risky`` prompts unless the risk
    is ``read``. ``auto`` never prompts. ``ask-irreversible`` prompts only
    when ``reversibility`` is ``irreversible``. When that argument is omitted,
    the floor for ``ask-irreversible`` is no prompt: the policy that classified
    the action asks at the point of no return, and it may still prompt more
    often than this helper.

    A ``PermissionPolicy`` may deny more often than this (including a hard
    deny with no prompt). It must not prompt less often than this for the
    configured autonomy level.
    """
    if autonomy is AutonomyLevel.ASK_ALWAYS:
        return True
    if autonomy is AutonomyLevel.AUTO:
        return False
    if autonomy is AutonomyLevel.ASK_IRREVERSIBLE:
        return reversibility is Reversibility.IRREVERSIBLE
    return risk is not RiskLevel.READ


@runtime_checkable
class PermissionPolicy(Protocol):
    """Decides whether an action needs a person, and how risky it is."""

    @property
    def autonomy(self) -> AutonomyLevel:
        """The configured autonomy level."""
        ...

    def classify(self, action: ActionRequest) -> RiskLevel:
        """Risk used for the decision.

        May agree with ``action.risk`` or raise it. Must not lower a
        ``destructive`` classification.
        """
        ...

    def requires_approval(self, action: ActionRequest) -> bool:
        """True when the user must be asked before the action runs."""
        ...


@runtime_checkable
class ApprovalPrompter(Protocol):
    """Asks a person. ``AutoApprovePrompter`` in ``tests/fakes.py`` is the test double."""

    def prompt(self, action: ActionRequest) -> bool:
        """Return True to allow the action, False to deny it."""
        ...


@runtime_checkable
class GrantStore(Protocol):
    """Remembers which permissions a plugin may use.

    Active grants are what ``PermissionPolicy`` reads. Suspended grants are
    kept for a later resume and are not active, so plugin-tagged actions stay
    denied. Implementations must not treat a grant as permission to lower a
    hard deny or a ``destructive`` risk; that decision stays in the policy.
    """

    def replace(self, plugin: str, permissions: Sequence[str], *, active: bool = True) -> None:
        """Set ``plugin``'s grants to exactly ``permissions``.

        When ``active`` is false, store them suspended so they are not applied.
        """
        ...

    def suspend(self, plugin: str) -> None:
        """Stop applying ``plugin``'s grants without forgetting them."""
        ...

    def resume(self, plugin: str) -> None:
        """Apply the grants previously suspended for ``plugin``."""
        ...

    def revoke(self, plugin: str) -> None:
        """Forget every grant for ``plugin``, active or suspended."""
        ...


class CommandResult(BaseModel):
    """Output of ``Sandbox.run``.

    On timeout, set ``timed_out=True`` and ``exit_code`` to
    ``TIMEOUT_EXIT_CODE`` (124). Do not raise for a timeout.
    """

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def resolve_sandbox_path(workdir: Path, path: str) -> Path:
    """Resolve ``path`` inside ``workdir``.

    Absolute paths, empty paths, and any path that leaves ``workdir``
    (including ``..`` and symlinks) raise ``SandboxError``. The returned path
    may not exist yet; ``write_file`` creates parents.
    """
    if not path or not path.strip():
        raise SandboxError("sandbox path is empty")
    root = workdir.resolve()
    candidate_base = Path(path)
    if candidate_base.is_absolute():
        raise SandboxError(f"sandbox path must stay inside the workdir: {path}")
    candidate = (root / candidate_base).resolve()
    if candidate != root and root not in candidate.parents:
        raise SandboxError(f"sandbox path escapes the workdir: {path}")
    return candidate


@runtime_checkable
class Sandbox(Protocol):
    """Run commands and read or write files in one isolated workdir.

    File contents are text (UTF-8). ``command`` is a shell command string;
    the safety agent decides how it is executed. Paths are relative to
    ``workdir``. Use ``resolve_sandbox_path`` for every file path.
    """

    @property
    def workdir(self) -> Path:
        """Isolated directory. All file access stays inside it."""
        ...

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        """Run ``command``. Honor ``timeout`` seconds when it is not None."""
        ...

    def read_file(self, path: str) -> str:
        """Return file text. Raise ``FileNotFoundError`` if it is missing."""
        ...

    def write_file(self, path: str, content: str) -> None:
        """Write file text, creating parent directories inside the workdir."""
        ...


class UndoResult(BaseModel):
    """What an undo restored, and what it could not.

    ``restored_to`` is ``run-start`` or a step id. ``irreversible`` lists
    actions whose effects are still out in the world. ``compensations_skipped``
    lists inverses that were declared but did not run.
    """

    run_id: str
    workdir: str
    restored_to: str
    files_changed: int = 0
    compensations_ran: list[str] = Field(default_factory=list)
    compensations_skipped: list[str] = Field(default_factory=list)
    irreversible: list[str] = Field(default_factory=list)


@runtime_checkable
class UndoController(Protocol):
    """Workspace snapshots and compensating actions for one run.

    The core loop calls this around steps. The implementation lives in
    ``swag_bot.safety`` so the loop does not import that package.
    """

    @property
    def auto_rollback(self) -> bool:
        """When true, a failed step restores the snapshot from its start."""
        ...

    def begin_run(self, run_id: str, workdir: Path) -> None:
        """Snapshot ``workdir`` before any step mutates it."""
        ...

    def begin_step(self, step_id: str) -> None:
        """Remember the workspace at the start of ``step_id``."""
        ...

    def note_action(self, action: ActionRequest, *, outcome: str | None = None) -> None:
        """Record an action so undo can compensate it or report that it cannot."""
        ...

    def rollback_step(self, step_id: str) -> UndoResult:
        """Restore the snapshot from the start of ``step_id`` and compensate."""
        ...

    def rollback_run(self, *, to_step: str | None = None) -> UndoResult:
        """Restore the run start, or the start of ``to_step`` when given."""
        ...


class ActionLogEntry(BaseModel):
    """One recorded action. The safety agent appends these; it does not delete them."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = Field(default_factory=_utcnow)
    action: ActionRequest
    autonomy: AutonomyLevel
    approved: bool
    approver: str
    outcome: str | None = None
    # Set when this action produced an ``Evidence`` record in the same run.
    evidence_id: str | None = None
    # Plan id of the run that recorded the action. Empty for entries written
    # outside a run. ``swag safety log`` reads the home index of these rows.
    run_id: str | None = None

    @field_validator("approver")
    @classmethod
    def _approver(cls, value: str) -> str:
        # "policy" when the policy allowed or denied with no prompt,
        # "user" when a prompter answered, "auto" when autonomy is auto.
        if not value.strip():
            raise ValueError("approver must not be empty")
        return value


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class MemoryItem(BaseModel):
    """One memory record. ``id`` is assigned by the store."""

    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


@runtime_checkable
class MemoryStore(Protocol):
    """Pluggable memory. ``search`` returns the most relevant items first.

    An empty query returns no items. ``get`` returns None when the id is
    missing. ``delete`` returns True only if the item existed.
    """

    def add(self, content: str, *, metadata: Mapping[str, Any] | None = None) -> MemoryItem:
        """Store ``content`` and return the new item."""
        ...

    def search(self, query: str, *, limit: int = 5) -> Sequence[MemoryItem]:
        """Return up to ``limit`` matches, best first."""
        ...

    def get(self, item_id: str) -> MemoryItem | None:
        """Return one item, or None if it is missing."""
        ...

    def delete(self, item_id: str) -> bool:
        """Delete one item. Return True if it existed."""
        ...


# ---------------------------------------------------------------------------
# Plan / do / verify
# ---------------------------------------------------------------------------


class Check(BaseModel):
    """One machine-checkable acceptance check for a plan step.

    ``kind`` is an open string so a newer writer does not make an older reader
    reject the plan. The reference runner in ``core/checks.py`` implements
    ``file_exists``, ``file_contains``, ``file_absent``, ``command``,
    ``exit_code``, and ``json_schema`` (see the Evidence Contract). An unknown
    kind fails that check at run time.

    ``schema`` in JSON is accepted as an alias of ``json_schema``.

    ``stdout`` checks compare captured command output. ``stdout_last_line`` is
    the exact last non-empty line. ``stdout_line_count`` is how many
    non-empty lines the output must have. Both default to unset so older
    checks still load.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    kind: str
    description: str = ""
    path: str | None = None
    command: str | None = None
    contains: str | None = None
    expected_exit: int | None = None
    json_schema: dict[str, Any] | None = None
    timeout: float | None = None
    stdout_last_line: str | None = None
    stdout_line_count: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _schema_alias(cls, value: Any) -> Any:
        if isinstance(value, dict) and "schema" in value and "json_schema" not in value:
            data = dict(value)
            data["json_schema"] = data.pop("schema")
            return data
        return value

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("check kind must not be empty")
        return text

    @field_validator("expected_exit", mode="before")
    @classmethod
    def _expected_exit(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.lstrip("-").isdigit():
                return int(text)
        return value


class CheckResult(BaseModel):
    """Outcome of one acceptance check. ``evidence_ids`` cite the ledger."""

    model_config = ConfigDict(extra="ignore")

    check_id: str
    passed: bool
    evidence_ids: list[str] = Field(default_factory=list)
    detail: str = ""


class Evidence(BaseModel):
    """One fact in a run's evidence ledger.

    Stdout, stderr, and file bodies are stored as blob files. The ``*_sha256``
    fields are the hex SHA-256 of those stored bytes. ``preview`` is a short
    redacted excerpt. ``stdout``, ``stderr``, and ``content`` are in-memory
    only and are omitted from ``run.jsonl``.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"ev-{uuid4().hex[:12]}")
    kind: str
    step_id: str | None = None
    attempt: int | None = None
    tool: str | None = None
    summary: str = ""
    exit_code: int | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    content_sha256: str | None = None
    stdout_blob: str | None = None
    stderr_blob: str | None = None
    content_blob: str | None = None
    path: str | None = None
    ok: bool | None = None
    detail: str = ""
    preview: str = ""
    duration_ms: int | None = None
    truncated: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    stdout: str = Field(default="", exclude=True)
    stderr: str = Field(default="", exclude=True)
    content: str = Field(default="", exclude=True)


class RunRecord(BaseModel):
    """One JSON line of a per-run ``run.jsonl`` file.

    ``record`` is ``header``, ``evidence``, ``action``, or ``check``.
    Only the payload that matches ``record`` is set.
    """

    model_config = ConfigDict(extra="ignore")

    record: str
    version: str | None = None
    spec: str | None = None
    run_id: str | None = None
    goal: str | None = None
    evidence: Evidence | None = None
    action: ActionLogEntry | None = None
    check: CheckResult | None = None


class StepStatus(StrEnum):
    """Where a plan step is in the plan-do-verify loop.

    ``done`` means the step ran and a check passed with cited evidence.
    ``failed`` means the work or an acceptance check failed. ``unverified``
    means a pass was claimed without evidence the harness could cite.
    ``skipped`` means a dependency did not succeed or the planner dropped
    the step.
    """

    PENDING = "pending"
    DOING = "doing"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    UNVERIFIED = "unverified"
    SKIPPED = "skipped"


class Step(BaseModel):
    """One step in a ``TaskPlan``. ``id`` is unique within the plan."""

    id: str
    title: str
    instruction: str = ""
    status: StepStatus = StepStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)

    @field_validator("id", "title")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("step id and title must not be empty")
        return value


class StepResult(BaseModel):
    """What happened when a step was executed and checked."""

    step_id: str
    status: StepStatus
    observation: str = ""
    error: str | None = None
    verified: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    check_results: list[CheckResult] = Field(default_factory=list)


class TaskPlan(BaseModel):
    """A goal broken into ordered steps. The core loop owns mutations of ``status``."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    goal: str
    steps: list[Step] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("goal")
    @classmethod
    def _goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be empty")
        return value

    @model_validator(mode="after")
    def _steps_consistent(self) -> TaskPlan:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique within a plan")
        known = set(ids)
        for step in self.steps:
            missing = [dep for dep in step.depends_on if dep not in known]
            if missing:
                raise ValueError(f"step {step.id} depends on unknown steps: {missing}")
        return self


@runtime_checkable
class AgentLoop(Protocol):
    """Plan, do, and verify one goal. ``PlanDoVerifyLoop`` in ``core`` is the stub."""

    def run(self, goal: str) -> TaskPlan:
        """Execute the loop and return the plan, including failed steps."""
        ...


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


class MCPServerSpec(BaseModel):
    """One server from a plugin ``.mcp.json`` ``mcpServers`` map.

    ``transport`` is ``stdio`` when ``command`` is set, or ``http`` / ``sse``
    / ``ws`` when ``url`` is set. ``headers`` is for streamable HTTP (values
    may still contain ``${VAR}`` placeholders; the client substitutes them).
    ``plugin`` is the plugin that declared the server, when the loader knows
    it. The mcp agent owns the real client.
    """

    name: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    transport: str = "stdio"
    plugin: str | None = None


@runtime_checkable
class MCPClient(Protocol):
    """Talks to one or more MCP servers.

    Tools are adapted to the shared ``Tool`` model so the core loop does not
    special-case MCP. ``call_tool`` returns text, same as ``ToolRegistry.call``.
    """

    def list_tools(self) -> Sequence[Tool]:
        """Tools currently offered by connected servers."""
        ...

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> str:
        """Invoke a tool by name. Raise ``KeyError`` if it is unknown."""
        ...

    def close(self) -> None:
        """Drop connections. Must be safe to call more than once."""
        ...


@runtime_checkable
class PluginRegistry(Protocol):
    """Skills, slash commands, sub-agents, and MCP configs from loaded plugins.

    The implementation lives in ``swag_bot.plugins``. Other packages should
    depend on this protocol instead of importing that package. ``list_*``
    methods are discovery-only: command and agent bodies stay empty, and
    skill metadata does not include ``SKILL.md`` instructions.
    ``load_command`` substitutes ``$ARGUMENTS``. ``select_skills`` ranks
    skill descriptions against a goal without calling a model.
    """

    def list_plugins(self) -> Sequence[Plugin]:
        """Plugins currently visible to the registry."""
        ...

    def list_skills(self) -> Sequence[SkillMeta]:
        """Level-1 metadata for plugin skills and standalone skills."""
        ...

    def load_skill(self, name: str) -> Skill:
        """Return one skill. Raise ``KeyError`` if ``name`` is unknown."""
        ...

    def list_commands(self) -> Sequence[SlashCommand]:
        """Slash commands. Bodies are empty until ``load_command``."""
        ...

    def load_command(self, name: str, arguments: str = "") -> SlashCommand:
        """Return one command with ``$ARGUMENTS`` applied. Raise ``KeyError`` if missing."""
        ...

    def list_agents(self) -> Sequence[AgentDefinition]:
        """Sub-agents. Bodies are empty until ``load_agent``."""
        ...

    def load_agent(self, name: str) -> AgentDefinition:
        """Return one sub-agent with its prompt body. Raise ``KeyError`` if missing."""
        ...

    def list_mcp_servers(self) -> Sequence[MCPServerSpec]:
        """MCP server specs parsed from plugins. Nothing is connected or spawned."""
        ...

    def select_skills(self, goal: str, *, limit: int = 5) -> Sequence[SkillMeta]:
        """Skills whose descriptions match ``goal``, best first. Empty if nothing matches."""
        ...


__all__ = [
    "TIMEOUT_EXIT_CODE",
    "ActionKind",
    "ActionLogEntry",
    "ActionRequest",
    "AgentDefinition",
    "AgentLoop",
    "ApprovalPrompter",
    "AutonomyLevel",
    "ChatChunk",
    "ChatResponse",
    "EVIDENCE_CONTRACT_SPEC",
    "EVIDENCE_CONTRACT_VERSION",
    "Check",
    "CheckResult",
    "CommandResult",
    "Evidence",
    "ExperimentalComponents",
    "GrantStore",
    "LLMClient",
    "MCPClient",
    "MCPServerSpec",
    "MemoryItem",
    "MemoryStore",
    "Message",
    "Permission",
    "PermissionPolicy",
    "Plugin",
    "PluginAuthor",
    "PluginChannel",
    "PluginDependency",
    "PluginManifest",
    "PluginRegistry",
    "Reversibility",
    "RiskLevel",
    "Role",
    "RunRecord",
    "Sandbox",
    "Skill",
    "SkillMeta",
    "SlashCommand",
    "Step",
    "StepResult",
    "StepStatus",
    "SWAG_TAINT_KEY",
    "StreamingLLMClient",
    "TaskPlan",
    "TaintTracker",
    "Tool",
    "ToolCall",
    "ToolRegistry",
    "TrustLevel",
    "UndoController",
    "UndoResult",
    "UserConfigOption",
    "default_requires_approval",
    "resolve_sandbox_path",
]
