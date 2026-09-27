"""Where Swag Bot is installed from.

``PYPI_PUBLISHED`` is the only switch. While it is false, every generated
command installs from ``GIT_INSTALL_URL``. Set it to true after the PyPI
project exists and the same commands use the package name alone.

``scripts/install.sh`` and ``scripts/install.ps1`` repeat these two values.
``tests/onboarding/test_distribution.py`` fails if they drift.
"""

from __future__ import annotations

PACKAGE_NAME = "swag-bot"
GIT_INSTALL_URL = "git+https://github.com/vishnu-Swagan/swag-bot"
PYPI_PUBLISHED = False

# Console script whose name matches the package, so ``uvx swag-bot`` works
# once the package is published. Declared in pyproject.toml.
CONSOLE_SCRIPT = "swag-bot"


def requirement(extras: str = "") -> str:
    """PEP 508 requirement for pip, uv, and uvx.

    ``extras`` is a comma-separated list such as ``"mcp"`` or ``"mcp,models"``.
    """
    name = PACKAGE_NAME if not extras else f"{PACKAGE_NAME}[{extras}]"
    if PYPI_PUBLISHED:
        return name
    return f"{name} @ {GIT_INSTALL_URL}"


def uvx_serve_args() -> list[str]:
    """Arguments after ``uvx`` that start ``swag serve-mcp`` with the MCP extra."""
    return ["--from", requirement("mcp"), CONSOLE_SCRIPT, "serve-mcp"]


def uv_tool_install_spec() -> str:
    """Requirement ``uv tool install`` should receive for a full local install."""
    return requirement("mcp,models")
