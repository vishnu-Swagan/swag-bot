"""``swag memory`` CLI against the JSON backend so tests stay offline."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.config import MemorySettings, Settings, save_settings
from swag_bot.memory.errors import MemoryError
from tests.cli_output import visible

runner = CliRunner()


@pytest.fixture()
def json_backend() -> None:
    save_settings(Settings(memory=MemorySettings(backend="json", path="memories.json")))


def test_add_search_list_forget(json_backend: None) -> None:
    added = runner.invoke(app, ["memory", "add", "ship the release", "--tag", "release"])
    assert added.exit_code == 0
    item_id = visible(added).strip()
    assert item_id

    found = runner.invoke(app, ["memory", "search", "release"])
    assert found.exit_code == 0
    found_text = visible(found)
    assert item_id in found_text
    assert "ship the release" in found_text
    assert "tags=release" in found_text

    listed = runner.invoke(app, ["memory", "list"])
    assert listed.exit_code == 0
    assert item_id in visible(listed)

    empty = runner.invoke(app, ["memory", "search", "   "])
    assert empty.exit_code == 0
    assert "no matches" in visible(empty)

    forgotten = runner.invoke(app, ["memory", "forget", item_id])
    assert forgotten.exit_code == 0
    assert f"forgot {item_id}" in visible(forgotten)
    missing = runner.invoke(app, ["memory", "forget", item_id])
    assert missing.exit_code == 1
    assert f"no memory {item_id}" in visible(missing)


def test_error_redacts_agentmemory_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_SECRET", "test-agentmemory-secret")

    def boom(config: object) -> object:
        raise MemoryError("server echoed test-agentmemory-secret")

    monkeypatch.setattr("swag_bot.memory.cli.get_memory_store", boom)
    result = runner.invoke(app, ["memory", "search", "hello"])
    assert result.exit_code == 1
    text = visible(result)
    assert "test-agentmemory-secret" not in text
    assert "$AGENTMEMORY_SECRET" in text
