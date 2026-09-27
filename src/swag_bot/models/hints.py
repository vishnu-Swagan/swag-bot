"""Messages for a missing local model.

``ollama/llama3.2`` is the default. A 404 from the daemon means the model was
never pulled, which a bare HTTP status does not say.
"""

from __future__ import annotations

from collections.abc import Sequence

from swag_bot.config import Settings


def model_matches(wanted: str, names: Sequence[str]) -> bool:
    """True when ``wanted`` is installed, including the ``name:latest`` tag."""
    target = wanted.strip().lower()
    if not target:
        return False
    for name in names:
        item = name.strip().lower()
        if not item:
            continue
        if item == target or item.startswith(target + ":"):
            return True
        bare = item.split(":", 1)[0]
        if bare == target:
            return True
    return False


def explain_ollama_http(status: int, detail: str, model: str) -> str:
    """Error text for a failed Ollama HTTP call, with a pull hint on 404."""
    body = detail.strip() or "(empty body)"
    message = f"ollama HTTP {status}: {body}"
    if model_missing(status, body):
        message += f". {pull_hint(model)}"
    return message


def model_missing(status: int, detail: str) -> bool:
    """True when Ollama is up but does not have this model."""
    text = detail.lower()
    if status == 404:
        return True
    return "not found" in text and "model" in text


def pull_hint(model: str) -> str:
    """The command a person runs to install ``model``."""
    return f"The model {model} is not installed. Pull it with: ollama pull {model}"


def availability_line(model: str, names: list[str] | None) -> str:
    """One line for ``swag model list`` and ``swag doctor``."""
    if names is None:
        return f"model check: ollama is unreachable, so {model} was not checked"
    if model_matches(model, names):
        return f"model check: {model} is available locally"
    return f"model check: {model} is not pulled. Run: ollama pull {model}"


def configured_model_line(settings: Settings) -> str | None:
    """Probe the configured Ollama model. Other providers are not checked here."""
    if settings.model.provider.strip().lower() != "ollama":
        return None
    from swag_bot.models.ollama import OllamaClient, resolve_ollama_base_url

    client = OllamaClient(
        model=settings.model.model,
        base_url=resolve_ollama_base_url(settings.model.api_base),
    )
    names = client.list_models(timeout=0.5)
    return availability_line(settings.model.model, names)
