"""Bring-your-own-key presence checks.

Values are read only to know whether a variable is non-empty, and to redact
those values out of error text. They are never written to config, logs, or
command output.
"""

from __future__ import annotations

import os

# Same names ``swag doctor`` reports. Order is the display order.
PROVIDER_ENV_VARS: tuple[tuple[str, str], ...] = (
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
)

# LiteLLM reads these itself when the model string is groq/, cerebras/, or
# mistral/. They are not in PROVIDER_ENV_VARS, which is the bring-your-own-key
# set the client looks up by provider name. They are redacted when set.
_EXTRA_SECRET_ENV_VARS = (
    "AGENTMEMORY_SECRET",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "MISTRAL_API_KEY",
)


def env_is_set(name: str) -> bool:
    """True when ``name`` is present and not only whitespace."""
    return bool(os.environ.get(name, "").strip())


def provider_api_key(provider: str) -> str | None:
    """Return the key for ``provider``, or None when it is unset.

    The string is for the outbound provider request only. Do not interpolate
    it into an error, a log line, or a settings file.
    """
    wanted = provider.strip().lower()
    for name, env_var in PROVIDER_ENV_VARS:
        if name == wanted and env_is_set(env_var):
            return os.environ[env_var]
    return None


def key_status() -> list[tuple[str, str, bool]]:
    """``(provider, env var, is_set)`` for each cloud provider. No key values."""
    return [(provider, env_var, env_is_set(env_var)) for provider, env_var in PROVIDER_ENV_VARS]


def redact_secrets(text: str) -> str:
    """Replace known secret values in ``text`` with the variable name."""
    redacted = text
    names = [env_var for _, env_var in PROVIDER_ENV_VARS]
    names.extend(_EXTRA_SECRET_ENV_VARS)
    for name in names:
        value = os.environ.get(name, "")
        if len(value) >= 4:
            redacted = redacted.replace(value, f"${name}")
    return redacted
