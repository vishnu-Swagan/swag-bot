"""Keep the screenshot fixture from leaking into the suite.

``SWAG_EXTENSION_FIXTURE=1`` is how store screenshots run a scripted plan.
A shell that still has that variable set must not change these tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_extension_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWAG_EXTENSION_FIXTURE", raising=False)
    monkeypatch.delenv("SWAG_EXTENSION_FIXTURE_DELAY", raising=False)
