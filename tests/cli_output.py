"""Plain-text views of CLI output.

Rich help paints each dash in an option on its own, so ``--dry-run`` is not a
contiguous substring while color is on. Comparisons use the stripped text.
"""

from __future__ import annotations

import re

# CSI / SGR sequences, including the ``\x1b[1;36m`` spans Typer puts on options.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences. Other characters stay where they are."""
    return _ANSI.sub("", text)


def visible(result: object) -> str:
    """Combined terminal output, without ANSI color.

    ``output`` already includes stdout and stderr. Fall back to those streams
    only when a result object has no combined output.
    """
    output = getattr(result, "output", None)
    if isinstance(output, str) and output:
        return strip_ansi(output)
    parts: list[str] = []
    for name in ("stdout", "stderr"):
        value = getattr(result, name, "") or ""
        parts.append(value if isinstance(value, str) else str(value))
    return strip_ansi("\n".join(parts))
