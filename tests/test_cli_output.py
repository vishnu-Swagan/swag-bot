"""ANSI stripping used by the CLI tests."""

from __future__ import annotations

from tests.cli_output import strip_ansi


def test_strip_ansi_rejoins_highlighted_options() -> None:
    raw = "\x1b[1;36m-\x1b[0m\x1b[1;36m-dry-run\x1b[0m"
    assert strip_ansi(raw) == "--dry-run"
    assert "--http" == strip_ansi("\x1b[1;36m-\x1b[0m\x1b[1;36m-http\x1b[0m")
