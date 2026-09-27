"""MCP server that exposes the browser tools on stdio.

The official ``mcp`` package is imported only when the server is built.
Chromium is launched on the first tool call, not at startup, so listing
tools does not need Playwright.
"""

from __future__ import annotations

from typing import Any

from swag_bot import __version__
from swag_bot.browser.catalog import TOOLS, BrowserTool
from swag_bot.browser.service import BrowserService
from swag_bot.errors import SwagError

_MCP_INSTALL = (
    "The optional mcp package is not installed. Install it with: pip install 'swag-bot[mcp]'"
)


def build_browser_mcp_server(service: BrowserService | None = None) -> Any:
    """MCP server whose tools match :data:`swag_bot.browser.catalog.TOOLS`."""
    try:
        from mcp.server.mcpserver import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise SwagError(_MCP_INSTALL) from exc

    active = service or BrowserService()
    server = MCPServer(
        "swag-browser",
        instructions=(
            "Headless browser for Swag Bot. "
            "navigate, submit, and download are network actions and need approval. "
            "snapshot and extract only read the page that is already open. "
            "Do not click a submit button or a link to a new domain; "
            "call submit or navigate so that action can be approved."
        ),
        version=__version__,
    )

    def annotations(tool: BrowserTool) -> Any:
        return ToolAnnotations(
            read_only_hint=tool.read_only,
            open_world_hint=tool.open_world,
            destructive_hint=False,
        )

    navigate = TOOLS["navigate"]

    @server.tool(
        name=navigate.name,
        description=navigate.description,
        annotations=annotations(navigate),
        meta=navigate.meta(),
    )
    def browser_navigate(url: str) -> str:
        """Open an http or https URL."""
        return active.call(navigate.name, url=url)

    snapshot = TOOLS["snapshot"]

    @server.tool(
        name=snapshot.name,
        description=snapshot.description,
        annotations=annotations(snapshot),
        meta=snapshot.meta(),
    )
    def browser_snapshot() -> str:
        """Read the open page."""
        return active.call(snapshot.name)

    click = TOOLS["click"]

    @server.tool(
        name=click.name,
        description=click.description,
        annotations=annotations(click),
        meta=click.meta(),
    )
    def browser_click(selector: str) -> str:
        """Click an element."""
        return active.call(click.name, selector=selector)

    type_text = TOOLS["type_text"]

    @server.tool(
        name=type_text.name,
        description=type_text.description,
        annotations=annotations(type_text),
        meta=type_text.meta(),
    )
    def browser_type_text(selector: str, text: str) -> str:
        """Type text into an element."""
        return active.call(type_text.name, selector=selector, text=text)

    fill = TOOLS["fill"]

    @server.tool(
        name=fill.name,
        description=fill.description,
        annotations=annotations(fill),
        meta=fill.meta(),
    )
    def browser_fill(selector: str, value: str) -> str:
        """Replace an input value."""
        return active.call(fill.name, selector=selector, value=value)

    submit = TOOLS["submit"]

    @server.tool(
        name=submit.name,
        description=submit.description,
        annotations=annotations(submit),
        meta=submit.meta(),
    )
    def browser_submit(selector: str, url: str) -> str:
        """Submit a form."""
        return active.call(submit.name, selector=selector, url=url)

    screenshot = TOOLS["screenshot"]

    @server.tool(
        name=screenshot.name,
        description=screenshot.description,
        annotations=annotations(screenshot),
        meta=screenshot.meta(),
    )
    def browser_screenshot(path: str) -> str:
        """Save a PNG screenshot."""
        return active.call(screenshot.name, path=path)

    extract = TOOLS["extract"]

    @server.tool(
        name=extract.name,
        description=extract.description,
        annotations=annotations(extract),
        meta=extract.meta(),
    )
    def browser_extract(selector: str, attribute: str = "") -> str:
        """Read text or one attribute."""
        return active.call(extract.name, selector=selector, attribute=attribute)

    download = TOOLS["download"]

    @server.tool(
        name=download.name,
        description=download.description,
        annotations=annotations(download),
        meta=download.meta(),
    )
    def browser_download(url: str, path: str) -> str:
        """Download a URL into the output directory."""
        return active.call(download.name, url=url, path=path)

    return server


def serve_stdio(service: BrowserService | None = None) -> None:
    """Serve the browser tools on stdin and stdout until the client disconnects."""
    server = build_browser_mcp_server(service)
    server.run("stdio")
