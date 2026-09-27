"""User-only key file under ``$SWAG_HOME``.

The file is mode 0600. Values are never printed. An environment variable
that is already set wins over the file.
"""

from __future__ import annotations

import os
from pathlib import Path

from swag_bot.config import swag_home
from swag_bot.onboarding.free_cloud import FREE_PROVIDERS

_ALLOWED = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        *(item.env_var for item in FREE_PROVIDERS),
    }
)


def secrets_path() -> Path:
    """Path of the key file for this ``SWAG_HOME``."""
    return swag_home() / "provider-keys.env"


def apply_saved_keys() -> None:
    """Copy saved keys into the environment when the variable is unset.

    A missing or unreadable file does nothing. Lines that are not an allowed
    variable name are ignored.
    """
    path = secrets_path()
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for name, value in _parse(text).items():
        if name not in _ALLOWED or not value:
            continue
        if os.environ.get(name, "").strip():
            continue
        os.environ[name] = value


def save_provider_key(env_var: str, value: str) -> Path:
    """Store one key. Creates the file as mode 0600. Raises ``ValueError`` if empty."""
    name = env_var.strip()
    secret = value.strip()
    if name not in _ALLOWED:
        raise ValueError(f"unsupported key name {name}")
    if not secret or "\n" in secret or "\r" in secret:
        raise ValueError("key must be a single non-empty line")
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.is_file():
        try:
            current = _parse(path.read_text(encoding="utf-8"))
        except OSError:
            current = {}
    current[name] = secret
    _write(path, current)
    os.chmod(path, 0o600)
    return path


def _parse(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name in _ALLOWED and value:
            found[name] = value
    return found


def _write(path: Path, keys: dict[str, str]) -> None:
    lines = [
        "# Swag Bot provider keys. Mode 0600. Do not commit or print this file.",
    ]
    for name in sorted(keys):
        lines.append(f"{name}={keys[name]}")
    payload = "\n".join(lines) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
