"""Headless browser tools for the browser plugin.

Playwright is an optional extra (``pip install 'swag-bot[browser]'``).
Importing this package does not launch a browser or import Playwright.
"""

from __future__ import annotations

from swag_bot.browser.catalog import PLUGIN_NAME, TOOLS

__all__ = ["PLUGIN_NAME", "TOOLS"]
