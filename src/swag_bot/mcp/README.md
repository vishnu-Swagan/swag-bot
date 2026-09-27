# mcp

**Owner:** the safety and MCP agent. You also own `src/swag_bot/safety/` and `tests/safety/`.

**Edit only:** `src/swag_bot/mcp/`, `src/swag_bot/safety/`, `tests/mcp/`, and `tests/safety/`.

You may update the `serve-mcp` wrapper in `src/swag_bot/cli.py` when the signature of `serve()` changes. Read `docs/ARCHITECTURE.md` before any other shared edit.

## What goes here

- An `MCPClient`. Adapt server tools to the shared `Tool` model so core never special-cases MCP. `call_tool` returns text.
- Read server commands and URLs from plugin `MCPServerSpec` values. Do not hardcode secrets. Environment values for a server come from the plugin config, not from this repo.
- `build_mcp_client(settings)` in `__init__.py`. Keep the name.
- `swag serve-mcp` / `swag mcp serve`: an MCP server that exposes Swag Bot. Implement `serve()` in `cli.py`. The root command delegates to it.
- `swag mcp tools` lists tools from connected servers.

The `mcp` Python package is an optional extra (`pip install -e ".[mcp]"`). Do not make it a required dependency.

## Status

Stub. `swag serve-mcp` and `swag mcp tools` exit 2.
