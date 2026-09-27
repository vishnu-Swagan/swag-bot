"""User settings from ``$SWAG_HOME/config.toml``.

``SWAG_HOME`` overrides the directory. When it is unset, the directory is
``~/.swag``. A missing file is not an error: ``load_settings`` returns the
defaults below. API keys are not settings. They stay in the environment
(see ``.env.example``) and this module never reads or writes them.

Example ``config.toml``::

    autonomy = "ask-risky"
    plugin_dirs = []

    [model]
    provider = "ollama"
    model = "llama3.2"
    harness = "auto"

    [model.fallback]
    provider = "ollama"
    model = "qwen2.5:7b"

    [model.budget]
    max_escalations = 1
    max_extra_seconds = 180
    max_cost_usd = 0

    [memory]
    backend = "memory"
    mode = "auto"

    [sandbox]
    mode = "local"
    image = "python:3.12-slim"
    network = false

    [evidence]
    enabled = true

    [undo]
    enabled = true
    auto_rollback = true

    [taint]
    enabled = true
    mode = "escalate"
    reader = "mark"
    workspace = "trusted"
    memory = "trusted"

    [escalation]
    enabled = false
    uncertainty_threshold = 0.6
    samples = 1
    jury = true
    jury_size = 3
    judges = []

    [bundle]
    record = false

    [skill_learning]
    mode = "review"   # off | review | auto
    replay = "same"   # same | varied

Known ``model.provider`` values: ``ollama`` (default), ``litellm``,
``openai``, ``anthropic``. The string is open so a new provider does not
require a schema change. ``memory.backend`` defaults to ``memory``, which
is the SQLite file ``$SWAG_HOME/memory.db``. ``memory.mode`` is ``auto``,
``ask``, or ``off``. ``sandbox.mode`` is ``off``, ``local``, or ``docker``.
``skill_learning.mode`` is ``off``, ``review`` (default), or ``auto``.
``skill_learning.replay`` is ``same`` (default) or ``varied``.
"""

from __future__ import annotations

import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from swag_bot.errors import ConfigError
from swag_bot.interfaces import AutonomyLevel, TrustLevel


class SandboxMode(StrEnum):
    """Where tool commands run. ``off`` refuses ``run``; file stubs may still be used."""

    OFF = "off"
    LOCAL = "local"
    DOCKER = "docker"


_HARNESS_MODES = frozenset({"auto", "off", "tiny", "standard", "frontier"})


class FallbackModelSettings(BaseModel):
    """Stronger model used only after a step fails, when the budget allows it.

    An empty ``provider`` or ``model`` turns escalation off. API keys are not
    stored here.
    """

    model_config = ConfigDict(extra="ignore")

    provider: str = ""
    model: str = ""
    api_base: str | None = None


class ModelBudgetSettings(BaseModel):
    """Limits on escalating a failing step.

    ``max_cost_usd`` of 0 still allows a local fallback, because its estimated
    cost is 0. A cloud fallback needs a budget above its estimated call cost.
    """

    model_config = ConfigDict(extra="ignore")

    max_escalations: int = 1
    max_extra_seconds: float = 180.0
    max_cost_usd: float = 0.0

    @field_validator("max_escalations")
    @classmethod
    def _escalations(cls, value: int) -> int:
        if value < 0:
            raise ValueError("model.budget.max_escalations must be >= 0")
        return value

    @field_validator("max_extra_seconds", "max_cost_usd")
    @classmethod
    def _non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("model budget limits must be >= 0")
        return value


class ModelSettings(BaseModel):
    """Which model to call. ``api_base`` empty or omitted means the provider default.

    ``timeout`` is the HTTP timeout in seconds. Omitted means the client
    default (120). The small-model harness raises that for local models when
    ``harness`` is not ``off``, and retries a timed-out request once.
    ``temperature``, ``num_ctx``, and ``num_predict`` are sent with each
    Ollama request (``num_ctx`` is filled from the harness probe when unset).
    ``harness`` is ``auto``, ``off``, ``tiny``, ``standard``, or ``frontier``.
    """

    model_config = ConfigDict(extra="ignore")

    provider: str = "ollama"
    model: str = "llama3.2"
    api_base: str | None = None
    timeout: float | None = None
    temperature: float = 0.2
    num_ctx: int | None = None
    num_predict: int = 4096
    harness: str = "auto"
    fallback: FallbackModelSettings = Field(default_factory=FallbackModelSettings)
    budget: ModelBudgetSettings = Field(default_factory=ModelBudgetSettings)

    @field_validator("harness")
    @classmethod
    def _harness(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in _HARNESS_MODES:
            raise ValueError(
                "model.harness must be one of: auto, off, tiny, standard, frontier"
            )
        return text

    @field_validator("timeout")
    @classmethod
    def _timeout(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("model.timeout must be greater than 0")
        return value

    @field_validator("temperature")
    @classmethod
    def _temperature(cls, value: float) -> float:
        if value < 0:
            raise ValueError("model.temperature must be >= 0")
        return value

    @field_validator("num_ctx")
    @classmethod
    def _num_ctx(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("model.num_ctx must be greater than 0")
        return value

    @field_validator("num_predict")
    @classmethod
    def _num_predict(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("model.num_predict must be greater than 0")
        return value


class MemorySettings(BaseModel):
    """``backend`` selects a ``MemoryStore``. ``path`` is for backends that use a file.

    ``mode`` controls reads and writes for a run: ``auto`` saves and says so,
    ``ask`` prompts first, ``off`` does neither. The default backend name
    ``memory`` stores rows in ``$SWAG_HOME/memory.db``.
    """

    model_config = ConfigDict(extra="ignore")

    backend: str = "memory"
    path: str | None = None
    mode: str = "auto"

    @field_validator("mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in {"ask", "auto", "off"}:
            raise ValueError("memory.mode must be ask, auto, or off")
        return text


class SandboxSettings(BaseModel):
    """Sandbox selection. ``image`` is the Docker image when ``mode`` is ``docker``."""

    model_config = ConfigDict(extra="ignore")

    mode: SandboxMode = SandboxMode.LOCAL
    image: str = "python:3.12-slim"
    network: bool = False


class EvidenceSettings(BaseModel):
    """Evidence ledger and execution-grounded checks.

    ``enabled`` is the default. Set it to false to judge a step from the
    model's text alone (the behavior from before the evidence ledger).
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True


class UndoSettings(BaseModel):
    """Workspace snapshots taken before file writes and shell commands.

    ``enabled`` defaults to true. ``auto_rollback`` restores a failed step's
    workspace to the snapshot from the start of that step. Neither setting
    changes the default autonomy, which stays ``ask-risky``.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    auto_rollback: bool = True


class TaintMode(StrEnum):
    """What to do when untrusted data would drive a sensitive action.

    ``escalate`` asks the user and shows the tainted source. ``block`` denies
    with no prompt. ``off`` does not label or enforce. ``auto`` autonomy has
    nobody to ask, so an escalated sink is denied instead of run.
    """

    OFF = "off"
    ESCALATE = "escalate"
    BLOCK = "block"


class TaintReader(StrEnum):
    """How untrusted tool output is shown to the model.

    ``mark`` keeps the text inside quarantine markers. ``strip`` drops
    instruction-shaped lines from that view. ``llm`` asks a tool-free reader
    for a JSON extract. The firewall still tracks the raw text either way.
    """

    MARK = "mark"
    STRIP = "strip"
    LLM = "llm"


class TaintSettings(BaseModel):
    """Taint firewall. See ``docs/TAINT.md`` for the threat model and limits."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    mode: TaintMode = TaintMode.ESCALATE
    reader: TaintReader = TaintReader.MARK
    workspace: TrustLevel = TrustLevel.TRUSTED
    memory: TrustLevel = TrustLevel.TRUSTED


class EscalationSettings(BaseModel):
    """Uncertainty questions and a jury before irreversible actions.

    ``enabled`` defaults to false, so a normal run does not ask extra questions
    or call extra models. ``samples`` is 1, which skips self-consistency calls.
    ``jury`` applies only when ``enabled`` is true. An empty ``judges`` list
    reuses the session model with separate prompts. See ``docs/ESCALATION.md``.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    uncertainty_threshold: float = 0.6
    samples: int = 1
    jury: bool = True
    jury_size: int = 3
    judges: list[str] = Field(default_factory=list)

    @field_validator("uncertainty_threshold")
    @classmethod
    def _threshold(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("escalation.uncertainty_threshold must be between 0 and 1")
        return float(value)

    @field_validator("samples", "jury_size")
    @classmethod
    def _panel_size(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("escalation.samples and escalation.jury_size must be from 1 to 5")
        return value


class BundleSettings(BaseModel):
    """Run bundles. ``record`` saves a portable bundle for every ``swag run``."""

    model_config = ConfigDict(extra="ignore")

    record: bool = False


class SkillLearningMode(StrEnum):
    """When a finished run may become an active skill.

    ``off`` does not distill. ``review`` (the default) writes a quarantined
    candidate and waits for ``swag skill promote``. ``auto`` promotes only
    when evidence verification and a replay both pass.
    """

    OFF = "off"
    REVIEW = "review"
    AUTO = "auto"


class SkillReplayTask(StrEnum):
    """Which task the promotion gate asks the replayer to run."""

    SAME = "same"
    VARIED = "varied"


class SkillLearningSettings(BaseModel):
    """Verification-gated skill learning. Both keys are optional in ``config.toml``."""

    model_config = ConfigDict(extra="ignore")

    mode: SkillLearningMode = SkillLearningMode.REVIEW
    replay: SkillReplayTask = SkillReplayTask.SAME


class Settings(BaseModel):
    """Top-level ``config.toml``. Unknown keys are ignored so new fields can land later."""

    model_config = ConfigDict(extra="ignore")

    model: ModelSettings = Field(default_factory=ModelSettings)
    autonomy: AutonomyLevel = AutonomyLevel.ASK_RISKY
    plugin_dirs: list[str] = Field(default_factory=list)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    evidence: EvidenceSettings = Field(default_factory=EvidenceSettings)
    undo: UndoSettings = Field(default_factory=UndoSettings)
    taint: TaintSettings = Field(default_factory=TaintSettings)
    escalation: EscalationSettings = Field(default_factory=EscalationSettings)
    bundle: BundleSettings = Field(default_factory=BundleSettings)
    skill_learning: SkillLearningSettings = Field(default_factory=SkillLearningSettings)


def swag_home() -> Path:
    """Directory that holds ``config.toml``. Overridden by ``SWAG_HOME``."""
    raw = os.environ.get("SWAG_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".swag"


def config_path() -> Path:
    """Path to ``config.toml`` for the current ``SWAG_HOME``."""
    return swag_home() / "config.toml"


def load_settings(path: Path | None = None) -> Settings:
    """Read settings. A missing file returns defaults. A bad file raises ``ConfigError``."""
    target = config_path() if path is None else path
    if not target.is_file():
        return Settings()
    try:
        with target.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"cannot read {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"cannot read {target}: top level must be a table")
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"cannot read {target}: {exc}") from exc


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    """Write settings as TOML. Creates the parent directory. Returns the path written."""
    target = config_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _strip_none(settings.model_dump(mode="json"))
    target.write_text(tomli_w.dumps(payload), encoding="utf-8")
    return target


def _strip_none(value: Any) -> Any:
    """Drop None values. TOML has no null, and omitted keys mean 'default'."""
    if isinstance(value, dict):
        return {key: _strip_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value
