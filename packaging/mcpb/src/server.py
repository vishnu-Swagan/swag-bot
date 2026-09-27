"""Claude Desktop entry point.

Starts ``swag serve-mcp`` and does not print anything first. Stdout is the
MCP channel.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Replace this process's arguments and run the Swag Bot CLI."""
    sys.argv = ["swag", "serve-mcp"]
    from swag_bot.cli import main as swag_main

    swag_main()


if __name__ == "__main__":
    main()
