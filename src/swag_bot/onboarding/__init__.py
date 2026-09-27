"""One-prompt setup: find a model, write config, and connect MCP clients.

This package is the one-prompt-setup workstream. It does not import the core
loop. ``swag run`` and ``swag serve-mcp`` call into it.
"""

from swag_bot.onboarding.distribution import GIT_INSTALL_URL, PACKAGE_NAME, PYPI_PUBLISHED

__all__ = ["GIT_INSTALL_URL", "PACKAGE_NAME", "PYPI_PUBLISHED"]
