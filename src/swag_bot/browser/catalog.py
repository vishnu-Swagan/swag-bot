"""Tool metadata for the browser plugin.

Playwright and the MCP SDK are not imported here. The MCP server and the
permission policy both read this table so the risk of a tool cannot drift
from the grant it requires.
"""

from __future__ import annotations

from dataclasses import dataclass

from swag_bot.interfaces import Permission, RiskLevel, Tool

PLUGIN_NAME = "browser"
SERVER_NAME = "browser"

# Visible text returned to the model. Screenshots and downloads are files.
TEXT_LIMIT = 8000
DOWNLOAD_LIMIT = 20 * 1024 * 1024


@dataclass(frozen=True)
class BrowserTool:
    """One browser action and the permission it requires."""

    name: str
    description: str
    risk: str
    permission: str
    read_only: bool = False
    open_world: bool = False

    def as_tool(self) -> Tool:
        """The ``Tool`` the executor sees after the MCP client prefixes the server name."""
        return Tool(
            name=public_name(self.name),
            description=self.description,
            risk_hint=self.risk,
            permission_hint=self.permission,
            plugin=PLUGIN_NAME,
        )

    def meta(self) -> dict[str, dict[str, str]]:
        """MCP ``_meta`` block. The client copies this onto the tool."""
        return {"swag": {"permission": self.permission, "risk": self.risk}}


def public_name(name: str) -> str:
    """Tool name published to the model: ``browser__navigate``."""
    return f"{SERVER_NAME}__{name}"


def _tool(
    name: str,
    description: str,
    *,
    risk: RiskLevel,
    permission: Permission,
    read_only: bool = False,
    open_world: bool = False,
) -> BrowserTool:
    return BrowserTool(
        name=name,
        description=description,
        risk=risk.value,
        permission=permission.value,
        read_only=read_only,
        open_world=open_world,
    )


TOOLS: dict[str, BrowserTool] = {
    tool.name: tool
    for tool in (
        _tool(
            "navigate",
            "Open an http or https URL in the headless browser. "
            "This is a network action. A host this session has not opened is a new domain: "
            "pass that URL here instead of clicking the link.",
            risk=RiskLevel.NETWORK,
            permission=Permission.NETWORK,
            open_world=True,
        ),
        _tool(
            "snapshot",
            "Read the open page: its title, URL, and visible text. "
            "Does not navigate or change the page.",
            risk=RiskLevel.READ,
            permission=Permission.MCP,
            read_only=True,
        ),
        _tool(
            "click",
            "Click an element by CSS selector. "
            "Refuses submit buttons and links that leave for a new domain. "
            "Use submit or navigate for those, so they can be approved.",
            risk=RiskLevel.EXECUTE,
            permission=Permission.MCP,
        ),
        _tool(
            "type_text",
            "Type text into an element by CSS selector. Does not submit the form.",
            risk=RiskLevel.WRITE,
            permission=Permission.MCP,
        ),
        _tool(
            "fill",
            "Replace the value of an input or textarea by CSS selector. Does not submit the form.",
            risk=RiskLevel.WRITE,
            permission=Permission.MCP,
        ),
        _tool(
            "submit",
            "Submit a form. Pass url as the page URL or the form action the user is approving. "
            "This sends data off the page and is a network action.",
            risk=RiskLevel.NETWORK,
            permission=Permission.NETWORK,
            open_world=True,
        ),
        _tool(
            "screenshot",
            "Save a PNG screenshot of the open page. "
            "path is relative to the browser output directory (SWAG_BROWSER_OUTPUT, or the "
            "current directory).",
            risk=RiskLevel.WRITE,
            permission=Permission.FILESYSTEM_WRITE,
        ),
        _tool(
            "extract",
            "Read the text, or one attribute, of the elements matching a CSS selector. "
            "Does not change the page.",
            risk=RiskLevel.READ,
            permission=Permission.MCP,
            read_only=True,
        ),
        _tool(
            "download",
            "Download an http or https URL into the browser output directory. "
            "path is a relative file name. This is a network action. "
            "Downloads larger than 20 MB are refused.",
            risk=RiskLevel.NETWORK,
            permission=Permission.NETWORK,
            open_world=True,
        ),
    )
}


def permissions_requested() -> list[str]:
    """Grants the plugin manifest asks for. Order is stable."""
    found = {tool.permission for tool in TOOLS.values()}
    return sorted(found)
