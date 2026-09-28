"""Model-size guesses and the timeouts and budgets that follow from them.

Sizes come from the model name (``qwen2.5:3b``). They are a prior for the
scaffold, not a measured parameter count.
"""

from __future__ import annotations

import re

_MOE = re.compile(r"(?i)(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*b")
_BILLIONS = re.compile(r"(?i)(?:^|[^a-z0-9])(\d+(?:\.\d+)?)\s*b(?:[^a-z0-9]|$)")

# Ollama's unsuffixed llama3.2 tag is the 3B model.
_KNOWN_BILLIONS = {
    "llama3.2": 3.0,
    "llama3.2:latest": 3.0,
    "phi3": 3.8,
    "phi3:mini": 3.8,
    "phi3:latest": 3.8,
}

_USD_PER_CALL = {
    "ollama": 0.0,
    "openai": 0.02,
    "anthropic": 0.03,
    "gemini": 0.01,
    "openrouter": 0.02,
    "litellm": 0.02,
}

# Big local models on CPU regularly outlive the client's historical 120s cap.
# A timed-out request is retried once, with a shorter reply cap, so these stay
# well under a 10 minute hang when num_predict is the local default.
_SMALL_LOCAL_TIMEOUT = 120.0
_LARGE_LOCAL_TIMEOUT = 180.0
# About 10 tokens/second on a CPU, plus slack for the prompt.
_SECONDS_PER_TOKEN = 0.1
_PROMPT_SLACK_SECONDS = 30.0
# Local models stay at this cap unless the user set model.timeout.
LOCAL_PREDICT_CAP = 1024


def parameter_billions(model: str) -> float | None:
    """Approximate parameter count in billions, parsed from ``model``."""
    moe = _MOE.search(model)
    if moe is not None:
        return float(moe.group(1)) * float(moe.group(2))
    match = _BILLIONS.search(model)
    if match is not None:
        return float(match.group(1))
    return _KNOWN_BILLIONS.get(model.strip().lower())


def local_num_predict(provider: str, configured: int, timeout: float | None) -> int:
    """Cap a local reply when the user did not set a longer timeout.

    An explicit ``model.timeout`` keeps ``configured`` so a long reply is
    allowed. Otherwise Ollama stays at ``LOCAL_PREDICT_CAP`` tokens.
    """
    if provider.strip().lower() != "ollama" or timeout is not None:
        return configured
    return min(configured, LOCAL_PREDICT_CAP)


def request_timeout_seconds(
    provider: str,
    model: str,
    configured: float | None,
    *,
    num_predict: int | None = None,
) -> float | None:
    """Timeout to use while the harness is on.

    An explicit ``model.timeout`` always wins. Otherwise local models get at
    least 120 seconds under 7B and 180 seconds at 7B and above. The timeout
    also grows with ``num_predict`` at about 10 tokens per second, so a long
    cap is not cut off at 180 seconds. A request that times out is retried
    once, with a shorter cap. Cloud providers keep the client default.
    """
    if configured is not None:
        return configured
    if provider.strip().lower() != "ollama":
        return None
    size = parameter_billions(model)
    floor = _LARGE_LOCAL_TIMEOUT if size is not None and size >= 7 else _SMALL_LOCAL_TIMEOUT
    if num_predict is None or num_predict <= 0:
        return floor
    generated = num_predict * _SECONDS_PER_TOKEN + _PROMPT_SLACK_SECONDS
    return max(floor, generated)


def estimate_cost_usd(provider: str) -> float:
    """Rough dollars for one escalated step. Local models are 0."""
    return _USD_PER_CALL.get(provider.strip().lower(), 0.02)


def estimate_seconds(provider: str, model: str) -> float:
    """Conservative seconds one escalated step may take, before it is called."""
    if provider.strip().lower() != "ollama":
        return 20.0
    size = parameter_billions(model)
    if size is not None and size >= 14:
        return 180.0
    if size is not None and size >= 7:
        return 120.0
    return 45.0
