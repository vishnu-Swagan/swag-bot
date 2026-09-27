"""JSON readiness report shared by ``swag doctor --json`` and ``swag setup``."""

from __future__ import annotations

from typing import Any

from swag_bot import __version__
from swag_bot.config import Settings, config_path, load_settings
from swag_bot.interfaces import AutonomyLevel
from swag_bot.onboarding.detect import (
    BYOK_CANDIDATES,
    EnvironmentSnapshot,
    capture_environment,
    model_is_installed,
)


def doctor_report(
    *,
    settings: Settings | None = None,
    snapshot: EnvironmentSnapshot | None = None,
) -> dict[str, Any]:
    """Readiness JSON. Key values are never included.

    ``ready`` is true when the configured Ollama tag is installed, or when
    the configured cloud provider's environment variable is set.
    """
    active = load_settings() if settings is None else settings
    facts = capture_environment() if snapshot is None else snapshot
    provider = active.model.provider.strip().lower()
    model = active.model.model
    if provider == "ollama":
        names = facts.ollama_models or []
        ready = facts.ollama_models is not None and model_is_installed(model, names)
        if ready:
            reason = f"Ollama has {model}."
        elif facts.ollama_models is None:
            reason = "Ollama did not answer, so the configured model is not available."
        else:
            reason = f"Ollama is running but {model} is not installed."
    else:
        env_var = _env_for(provider)
        ready = bool(env_var and facts.keys.get(env_var, False))
        if env_var is None:
            reason = f"Provider {provider} is not a known bring-your-own-key provider."
        elif ready:
            reason = f"{env_var} is set."
        else:
            reason = f"{env_var} is unset."
    path = config_path()
    return {
        "autonomy": active.autonomy.value
        if isinstance(active.autonomy, AutonomyLevel)
        else str(active.autonomy),
        "config_file": str(path),
        "config_present": path.is_file(),
        "model": model,
        "provider": provider,
        "ready": ready,
        "reason": reason,
        "version": __version__,
    }


def _env_for(provider: str) -> str | None:
    for name, env_var, _model in BYOK_CANDIDATES:
        if name == provider:
            return env_var
    return None
