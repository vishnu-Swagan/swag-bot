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

    [memory]
    backend = "memory"

    [sandbox]
    mode = "local"
    image = "python:3.12-slim"
    network = false

Known ``model.provider`` values: ``ollama`` (default), ``litellm``,
``openai``, ``anthropic``. The string is open so a new provider does not
require a schema change. ``memory.backend`` defaults to ``memory``
(process-local). ``sandbox.mode`` is ``off``, ``local``, or ``docker``.
"""

from __future__ import annotations

import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from swag_bot.errors import ConfigError
from swag_bot.interfaces import AutonomyLevel


class SandboxMode(StrEnum):
    """Where tool commands run. ``off`` refuses ``run``; file stubs may still be used."""

    OFF = "off"
    LOCAL = "local"
    DOCKER = "docker"


class ModelSettings(BaseModel):
    """Which model to call. ``api_base`` empty or omitted means the provider default."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "ollama"
    model: str = "llama3.2"
    api_base: str | None = None


class MemorySettings(BaseModel):
    """``backend`` selects a ``MemoryStore``. ``path`` is for backends that use a file."""

    model_config = ConfigDict(extra="ignore")

    backend: str = "memory"
    path: str | None = None


class SandboxSettings(BaseModel):
    """Sandbox selection. ``image`` is the Docker image when ``mode`` is ``docker``."""

    model_config = ConfigDict(extra="ignore")

    mode: SandboxMode = SandboxMode.LOCAL
    image: str = "python:3.12-slim"
    network: bool = False


class Settings(BaseModel):
    """Top-level ``config.toml``. Unknown keys are ignored so new fields can land later."""

    model_config = ConfigDict(extra="ignore")

    model: ModelSettings = Field(default_factory=ModelSettings)
    autonomy: AutonomyLevel = AutonomyLevel.ASK_RISKY
    plugin_dirs: list[str] = Field(default_factory=list)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)


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
