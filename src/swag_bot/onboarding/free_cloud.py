"""Free-plan cloud providers LiteLLM can call when nothing local is running.

Prompts leave the machine. Rate limits change, so this module links to each
provider's page and does not copy a number. Checked on 2026-09-27.
"""

from __future__ import annotations

from dataclasses import dataclass

# GitHub's own docs: the Models catalog and inference API were retired.
GITHUB_MODELS_RETIRED = (
    "GitHub Models was retired on 2026-07-30. The playground and inference API "
    "are gone, so a GitHub token is not offered here. "
    "https://docs.github.com/en/github-models"
)

CLOUD_WARNING = (
    "A free cloud plan sends your prompts to that provider. "
    "That is not private, unlike Ollama, LM Studio, Jan, llama.cpp, llamafile, "
    "or GPT4All on this machine. Free plans also rate-limit; the limit is on "
    "the provider's page, and it changes, so Swag Bot does not copy the number."
)


@dataclass(frozen=True)
class FreeProvider:
    """One menu row. ``provider`` is the config provider name."""

    menu_id: str
    title: str
    env_var: str
    provider: str
    model: str
    key_url: str
    limits_url: str


# Order is the menu order. Gemini and OpenRouter are also in BYOK_CANDIDATES
# so an already-exported key is picked before this menu.
FREE_PROVIDERS: tuple[FreeProvider, ...] = (
    FreeProvider(
        menu_id="gemini",
        title="Google Gemini (AI Studio)",
        env_var="GEMINI_API_KEY",
        provider="gemini",
        model="gemini-2.5-flash",
        key_url="https://aistudio.google.com/apikey",
        limits_url="https://ai.google.dev/gemini-api/docs/rate-limits",
    ),
    FreeProvider(
        menu_id="groq",
        title="Groq",
        env_var="GROQ_API_KEY",
        provider="litellm",
        model="groq/llama-3.3-70b-versatile",
        key_url="https://console.groq.com/keys",
        limits_url="https://console.groq.com/docs/rate-limits",
    ),
    FreeProvider(
        menu_id="openrouter",
        title="OpenRouter free router",
        env_var="OPENROUTER_API_KEY",
        provider="openrouter",
        model="openrouter/free",
        key_url="https://openrouter.ai/keys",
        limits_url="https://openrouter.ai/docs/api/reference/limits",
    ),
    FreeProvider(
        menu_id="cerebras",
        title="Cerebras",
        env_var="CEREBRAS_API_KEY",
        provider="litellm",
        model="cerebras/gpt-oss-120b",
        key_url="https://cloud.cerebras.ai",
        limits_url="https://inference-docs.cerebras.ai/models/overview",
    ),
    FreeProvider(
        menu_id="mistral",
        title="Mistral",
        env_var="MISTRAL_API_KEY",
        provider="litellm",
        model="mistral/mistral-small-latest",
        key_url="https://console.mistral.ai/api-keys/",
        limits_url=(
            "https://docs.mistral.ai/getting-started/quickstarts/studio/activate-and-generate-api-key"
        ),
    ),
)


def provider_by_menu_id(menu_id: str) -> FreeProvider | None:
    """Match a menu number (1-based) or a short name. Unknown returns None."""
    text = menu_id.strip().lower()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(FREE_PROVIDERS):
            return FREE_PROVIDERS[index]
        return None
    for item in FREE_PROVIDERS:
        if text == item.menu_id:
            return item
    return None


def menu_text() -> str:
    """The choices, the privacy warning, and the GitHub Models retirement note."""
    lines = [CLOUD_WARNING, "Free cloud choices:"]
    for index, item in enumerate(FREE_PROVIDERS, start=1):
        lines.append(
            f"  {index}. {item.title} — key: {item.key_url} — limits: {item.limits_url}"
        )
    lines.append(GITHUB_MODELS_RETIRED)
    lines.append("Model notes: https://github.com/vishnu-Swagan/swag-bot/blob/main/docs/MODELS.md")
    return "\n".join(lines)


def env_defaults() -> tuple[tuple[str, str, str], ...]:
    """``(provider, env var, model)`` for keys that are already exported."""
    return tuple((item.provider, item.env_var, item.model) for item in FREE_PROVIDERS)
