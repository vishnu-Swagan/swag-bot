"""``swag browser-mcp``: serve the headless browser over MCP stdio."""

from __future__ import annotations

import sys

import typer

from swag_bot.errors import SwagError


def browser_mcp() -> None:
    """Serve headless browser tools over MCP stdio.

    The plugin's ``.mcp.json`` runs this command. Chromium starts on the
    first browser action. Install Playwright with ``pip install
    'swag-bot[browser]'`` and ``python -m playwright install chromium``.
    """
    try:
        from swag_bot.browser.server import serve_stdio

        serve_stdio()
    except SwagError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(code=2) from exc
