"""Shared exceptions.

Area-specific errors live in the package that owns them. Add a subclass here
only when every area needs to catch it. New subclasses are fine; renaming or
removing one is a breaking change.
"""

from __future__ import annotations

import sys


class SwagError(Exception):
    """Base class for errors Swag Bot raises on purpose."""


class ConfigError(SwagError):
    """``config.toml`` could not be parsed or did not match the schema."""


class SandboxError(SwagError):
    """A sandbox path escaped the workdir, or a sandbox command was rejected."""


class NotImplementedYet(SwagError):
    """Raised by foundation stubs. The owning agent replaces the caller."""

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(
            f"{feature} is not implemented yet. See docs/ARCHITECTURE.md for who owns it."
        )


def unimplemented(feature: str) -> None:
    """Print a stub message and exit 2.

    CLI commands call this until the owning agent fills them in. The process
    exit code is 2 so a script can tell "not built" from a successful run.
    """
    print(str(NotImplementedYet(feature)), file=sys.stderr)
    raise SystemExit(2)
