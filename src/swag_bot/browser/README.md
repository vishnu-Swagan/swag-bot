# browser

Headless browser tools for the `browser` plugin. Playwright is optional.
This package does not import it, or the MCP SDK, until a browser is launched
or `swag browser-mcp` starts.

`catalog.py` is the list of tools, the risk of each one, and the grant it
requires. `session.py` performs the actions against a page port so tests can
use a fake. `playwright_page.py` is the real page. `server.py` publishes the
tools over MCP stdio.

The plugin the agent installs is `plugins/browser/`. Read that README for
install, permissions, and the sandbox trade-off.
