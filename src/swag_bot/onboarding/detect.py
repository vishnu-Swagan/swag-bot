"""Detect a bring-your-own-key provider or a local Ollama model.

No API key value is returned or logged. Ollama is probed with a short HTTP
timeout and is never installed by this module.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Same providers ``swag_bot.models.keys.PROVIDER_ENV_VARS`` teaches the
# LiteLLM client to read. A test checks the names still match.
BYOK_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("anthropic", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-latest"),
    ("openai", "OPENAI_API_KEY", "gpt-4o-mini"),
    ("gemini", "GEMINI_API_KEY", "gemini-2.0-flash"),
    ("openrouter", "OPENROUTER_API_KEY", "openai/gpt-4o-mini"),
)

# qwen2.5:7b is the default pull. A 3B model failed in the owner's testing.
# The size label matches the Ollama library page (about 4.7 GB) as of 2026-09-27.
RECOMMENDED_MODEL = "qwen2.5:7b"
RECOMMENDED_SIZE_LABEL = "about 4.7 GB"
MIN_SUITABLE_BILLIONS = 7.0
# A 7B Q4 model needs several gigabytes resident. Below this, do not offer a pull.
MIN_PULL_RAM_BYTES = 6 * 1024 * 1024 * 1024
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
PROBE_TIMEOUT_SECONDS = 0.4

ActionName = Literal["configure", "pull", "stop"]
ProgressFn = Callable[[str], None]


@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Facts setup is allowed to see. Key values are booleans, never strings."""

    keys: dict[str, bool]
    google_api_key_set: bool
    ollama_installed: bool
    ollama_models: list[str] | None
    mem_bytes: int | None


@dataclass(frozen=True)
class Decision:
    """What ``swag setup --auto`` should do next."""

    action: ActionName
    provider: str
    model: str
    message: str


def capture_environment(*, timeout: float = PROBE_TIMEOUT_SECONDS) -> EnvironmentSnapshot:
    """Read the local machine. Network use is one short request to Ollama."""
    keys = {env_var: _env_set(env_var) for _, env_var, _ in BYOK_CANDIDATES}
    return EnvironmentSnapshot(
        keys=keys,
        google_api_key_set=_env_set("GOOGLE_API_KEY"),
        ollama_installed=shutil.which("ollama") is not None,
        ollama_models=fetch_ollama_models(timeout=timeout),
        mem_bytes=read_mem_bytes(),
    )


def decide(snapshot: EnvironmentSnapshot) -> Decision:
    """Pick BYOK, an installed 7B-class model, a pull, or a stop hint.

    Order matches the one-prompt design: a cloud key wins, then a suitable
    local model, then a pull of ``qwen2.5:7b`` after the user agrees, then
    an install hint. A 3B-only Ollama install is not treated as ready.
    """
    for provider, env_var, model in BYOK_CANDIDATES:
        if snapshot.keys.get(env_var):
            return Decision(
                action="configure",
                provider=provider,
                model=model,
                message=(
                    f"Using {provider} model {model} because {env_var} is set. "
                    "The key stays in the environment and is not written to config."
                ),
            )

    installed = choose_installed(snapshot.ollama_models or [])
    if installed is not None:
        return Decision(
            action="configure",
            provider="ollama",
            model=installed,
            message=f"Using local Ollama model {installed}.",
        )

    if snapshot.ollama_models is not None:
        if snapshot.mem_bytes is not None and snapshot.mem_bytes < MIN_PULL_RAM_BYTES:
            return Decision(
                action="stop",
                provider="ollama",
                model="",
                message=(
                    "Ollama is running but has no 7B-class model, and this machine "
                    "has under 6 GB of RAM. A 3B model is not used: it failed in testing. "
                    "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or "
                    "OPENROUTER_API_KEY, or run on a machine with more memory."
                    + _google_hint(snapshot)
                ),
            )
        listed = ", ".join(snapshot.ollama_models) if snapshot.ollama_models else "none"
        return Decision(
            action="pull",
            provider="ollama",
            model=RECOMMENDED_MODEL,
            message=(
                f"Ollama is running. Installed models: {listed}. "
                f"Swag Bot can pull {RECOMMENDED_MODEL} ({RECOMMENDED_SIZE_LABEL}). "
                "3B models are not selected."
                + _google_hint(snapshot)
            ),
        )

    if not snapshot.ollama_installed:
        hint = (
            "Ollama is not on PATH and no API key is set. "
            "Install Ollama from https://ollama.com/download (Linux: "
            "curl -fsSL https://ollama.com/install.sh | sh), start it, and re-run "
            "swag setup --auto. Swag Bot does not install system software itself."
        )
    else:
        hint = (
            "The ollama binary is on PATH but the daemon did not answer at "
            f"{ollama_base_url()}. Start it with `ollama serve`, then re-run "
            "swag setup --auto."
        )
    return Decision(
        action="stop",
        provider="ollama",
        model="",
        message=hint + _google_hint(snapshot),
    )


def choose_installed(names: list[str]) -> str | None:
    """Smallest installed model of at least 7B, preferring ``qwen2.5:7b``."""
    ranked: list[tuple[float, str]] = []
    for name in names:
        size = parameter_billions(name)
        if size is not None and size >= MIN_SUITABLE_BILLIONS:
            ranked.append((size, name))
    if not ranked:
        return None
    for _, name in ranked:
        if name.startswith("qwen2.5:7b"):
            return name
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][1]


def parameter_billions(name: str) -> float | None:
    """Parse a size token such as ``7b`` or ``8b`` from an Ollama tag."""
    lowered = name.lower()
    token = ""
    for char in lowered:
        if char.isdigit() or (char == "." and token and "." not in token):
            token += char
            continue
        if char == "b" and token:
            try:
                return float(token)
            except ValueError:
                return None
        token = ""
    return None


def model_is_installed(wanted: str, names: list[str]) -> bool:
    """True when ``wanted`` is a tag or the bare family of an installed tag."""
    target = wanted.strip()
    if not target:
        return False
    for name in names:
        if name == target:
            return True
        if ":" not in target and name.split(":", 1)[0] == target:
            return True
    return False


def ollama_base_url() -> str:
    """Host the Ollama client uses: ``OLLAMA_HOST`` or the local default."""
    raw = os.environ.get("OLLAMA_HOST", "").strip()
    if not raw:
        return DEFAULT_OLLAMA_HOST
    if "://" not in raw:
        raw = "http://" + raw
    return raw.rstrip("/")


def fetch_ollama_models(*, timeout: float = PROBE_TIMEOUT_SECONDS) -> list[str] | None:
    """Names from ``/api/tags``, or None when the daemon does not answer."""
    url = f"{ollama_base_url()}/api/tags"
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - local daemon URL
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    names: list[str] = []
    for item in payload.get("models") or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def pull_ollama_model(
    name: str,
    *,
    timeout: float = 120.0,
    on_progress: ProgressFn | None = None,
) -> None:
    """Pull ``name`` via ``POST /api/pull``. Raises ``OSError`` on failure.

    Progress lines are handed to ``on_progress``. They are not written to
    stdout by this function.
    """
    body = json.dumps({"name": name, "stream": True}).encode("utf-8")
    request = Request(
        f"{ollama_base_url()}/api/pull",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local daemon URL
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if on_progress is not None:
                    on_progress(_progress_line(line))
                _raise_if_pull_error(line)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise OSError(f"could not pull {name} from Ollama: {exc}") from exc


def read_mem_bytes() -> int | None:
    """Total RAM from ``/proc/meminfo``, or None when it cannot be read."""
    path = Path("/proc/meminfo")
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1]) * 1024
    return None


def _env_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _google_hint(snapshot: EnvironmentSnapshot) -> str:
    if snapshot.google_api_key_set and not snapshot.keys.get("GEMINI_API_KEY", False):
        return (
            " GOOGLE_API_KEY is set, but Swag Bot's Gemini client reads GEMINI_API_KEY. "
            "Export that name to use Gemini."
        )
    return ""


def _progress_line(line: str) -> str:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(payload, dict):
        return line
    status = payload.get("status")
    if isinstance(status, str) and status:
        return status
    return line


def _raise_if_pull_error(line: str) -> None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return
    if isinstance(payload, dict) and payload.get("error"):
        raise OSError(str(payload["error"]))
