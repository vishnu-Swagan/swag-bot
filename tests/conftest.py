"""Keep tests off the real ``~/.swag`` directory and off colored CLI output.

Typer turns color on when ``GITHUB_ACTIONS`` or ``FORCE_COLOR`` is set, and it
reads that decision once, at import. Rich then styles each ``-`` in an option
separately, so ``"--dry-run" in result.output`` fails. ``NO_COLOR`` alone does
not stop that once the terminal has been forced on. This module clears the
forced-color environment before Typer is imported, and each test reinforces it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.cli_output import strip_ansi

# Applied at import, before test modules import Typer.
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
os.environ["COLUMNS"] = "200"
for _color_var in ("FORCE_COLOR", "PY_COLORS", "GITHUB_ACTIONS"):
    os.environ.pop(_color_var, None)


def _plain_text_property(original: Callable[..., str]) -> property:
    def getter(self: object) -> str:
        return strip_ansi(original(self))

    return property(getter)


@pytest.fixture(autouse=True)
def _plain_cli_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable Rich/Typer color and strip ANSI from captured CLI results."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("_TYPER_FORCE_DISABLE_TERMINAL", "1")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("PY_COLORS", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    import typer.rich_utils as rich_utils
    from typer.testing import Result

    # ``None`` is Typer's own switch for "do not color". ``FORCE_TERMINAL`` was
    # frozen at import if the runner had already set ``GITHUB_ACTIONS``.
    monkeypatch.setattr(rich_utils, "COLOR_SYSTEM", None)
    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", False)
    for name in ("output", "stdout", "stderr"):
        current = getattr(Result, name)
        original = current.fget
        if original is None:
            continue
        monkeypatch.setattr(Result, name, _plain_text_property(original))


@pytest.fixture(autouse=True)
def _isolated_swag_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / "swag-home"
    home.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    yield home
