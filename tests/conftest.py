"""Keep tests off the real ``~/.swag`` directory."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_swag_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / "swag-home"
    home.mkdir()
    monkeypatch.setenv("SWAG_HOME", str(home))
    yield home
