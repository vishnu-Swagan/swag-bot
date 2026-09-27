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

    ``ready`` is true when the configured Ollama tag is installed, when a
    local OpenAI-compatible server lists the configured model, or when the
    configured cloud provider's environment variable is set.
    """
    active = load_settings() if settings is None else settings
    if snapshot is None:
        facts = capture_environment(extra_base=active.model.api_base)
    else:
        facts = snapshot
    provider = active.model.provider.strip().lower()
    model = active.model.model
    ready, reason = _readiness(provider, model, active.model.api_base, facts)
    path = config_path()
    report: dict[str, Any] = {
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
    if active.model.api_base:
        report["api_base"] = active.model.api_base
    return report


def _readiness(
    provider: str,
    model: str,
    api_base: str | None,
    facts: EnvironmentSnapshot,
) -> tuple[bool, str]:
    if provider == "ollama":
        names = facts.ollama_models or []
        ready = facts.ollama_models is not None and model_is_installed(model, names)
        if ready:
            return True, f"Ollama has {model}."
        if facts.ollama_models is None:
            return False, "Ollama did not answer, so the configured model is not available."
        return False, f"Ollama is running but {model} is not installed."
    if provider == "litellm" and api_base:
        return _local_ready(model, api_base, facts)
    env_var = _env_for(provider, model)
    ready = bool(env_var and facts.keys.get(env_var, False))
    if env_var is None:
        return False, f"Provider {provider} is not a known bring-your-own-key provider."
    if ready:
        return True, f"{env_var} is set."
    return False, f"{env_var} is unset."


def _local_ready(model: str, api_base: str, facts: EnvironmentSnapshot) -> tuple[bool, str]:
    from swag_bot.onboarding.local_servers import normalize_base_url

    try:
        wanted_base = normalize_base_url(api_base)
    except ValueError:
        return False, "model.api_base is not a valid URL."
    model_id = model[len("openai/") :] if model.startswith("openai/") else model
    for item in facts.local_servers:
        if item.base_url == wanted_base and model_id in item.model_ids:
            return True, f"{item.name} at {wanted_base} lists {model_id}."
    return False, f"No server at {wanted_base} listed {model_id}."


def _env_for(provider: str, model: str = "") -> str | None:
    for name, env_var, _model in BYOK_CANDIDATES:
        if name == provider:
            return env_var
    if provider != "litellm":
        return None
    from swag_bot.onboarding.free_cloud import FREE_PROVIDERS

    for item in FREE_PROVIDERS:
        if item.provider == "litellm" and model == item.model:
            return item.env_var
    return None
