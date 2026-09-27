"""Install, enable, disable, and remove plugins on a local Swag home."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.config import Settings
from swag_bot.interfaces import ActionRequest, RiskLevel
from swag_bot.plugins.catalog import discover_plugins
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.installer import (
    install_plugin,
    list_installed,
    parse_install_source,
    redact_secrets,
    remove_plugin,
    set_enabled,
)
from tests.fakes import AutoApprovePrompter
from tests.plugins.helpers import write_plugin


class DenyPrompter:
    def __init__(self) -> None:
        self.actions: list[ActionRequest] = []

    def prompt(self, action: ActionRequest) -> bool:
        self.actions.append(action)
        return False


def test_parse_github_owner_repo_ref() -> None:
    parsed = parse_install_source("acme/tools@v1.2.0")
    assert parsed.url == "https://github.com/acme/tools.git"
    assert parsed.ref == "v1.2.0"
    local = parse_install_source("./plugins/example-github-helper")
    assert local.path == Path("./plugins/example-github-helper")


def test_install_enable_disable_remove(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = write_plugin(
        tmp_path / "src" / "demo-plugin",
        permissions=["filesystem.read", "network"],
        agent=True,
    )
    prompter = AutoApprovePrompter()
    record = install_plugin(str(source), prompter=prompter, home=home)
    assert record.name == "demo-plugin"
    assert record.enabled is True
    assert record.permissions == ["filesystem.read", "network"]
    assert len(prompter.prompts) == 1
    action = prompter.prompts[0]
    assert action.arguments["permissions"] == ["filesystem.read", "network"]
    assert "filesystem.read" in action.summary
    assert action.risk is RiskLevel.NETWORK
    installed = home / "plugins" / "demo-plugin" / ".claude-plugin" / "plugin.json"
    assert installed.is_file()
    assert (home / "plugins" / "registry.json").is_file()

    settings = Settings()
    names = [plugin.manifest.name for plugin in discover_plugins(settings, home=home)]
    assert names == ["demo-plugin"]

    set_enabled("demo-plugin", False, home=home)
    assert discover_plugins(settings, home=home) == []
    assert list_installed(home=home)[0].enabled is False

    set_enabled("demo-plugin", True, home=home)
    assert [plugin.manifest.name for plugin in discover_plugins(settings, home=home)] == [
        "demo-plugin"
    ]

    remove_plugin("demo-plugin", home=home)
    assert list_installed(home=home) == []
    assert not (home / "plugins" / "demo-plugin").exists()
    with pytest.raises(PluginError, match="not installed"):
        remove_plugin("demo-plugin", home=home)


def test_permission_prompt_denial_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = write_plugin(tmp_path / "src", permissions=["shell", "secrets"])
    prompter = DenyPrompter()
    with pytest.raises(PluginError, match="installation denied"):
        install_plugin(str(source), prompter=prompter, home=home)
    assert prompter.actions[0].arguments["permissions"] == ["shell", "secrets"]
    assert prompter.actions[0].risk is RiskLevel.DESTRUCTIVE
    assert not (home / "plugins" / "demo-plugin").exists()
    assert not (home / "plugins" / "registry.json").exists()


def test_yes_skips_prompter(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = write_plugin(tmp_path / "src", permissions=[])
    seen: list[ActionRequest] = []
    record = install_plugin(
        str(source),
        assume_yes=True,
        home=home,
        announce=seen.append,
        prompter=DenyPrompter(),
    )
    assert record.name == "demo-plugin"
    assert seen[0].arguments["permissions"] == []
    assert "none" in seen[0].summary


def test_default_enabled_false(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = write_plugin(tmp_path / "src", default_enabled=False)
    install_plugin(str(source), assume_yes=True, home=home)
    assert list_installed(home=home)[0].enabled is False
    assert discover_plugins(Settings(), home=home) == []


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = write_plugin(tmp_path / "src")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (source / "linked").symlink_to(outside)
    with pytest.raises(PluginError, match="symlink escapes"):
        install_plugin(str(source), assume_yes=True, home=home)
    assert list_installed(home=home) == []
    assert not (home / "plugins" / "demo-plugin").exists()


def test_plugin_dirs_override_installed_copy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    installed_src = write_plugin(tmp_path / "installed-src", version="1.0.0")
    install_plugin(str(installed_src), assume_yes=True, home=home)
    checkout = write_plugin(tmp_path / "checkout", version="2.0.0")
    found = discover_plugins(Settings(plugin_dirs=[str(checkout)]), home=home)
    assert found[0].manifest.version == "2.0.0"
    assert len(found) == 1


def test_git_owner_repo_uses_clone(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cloned: list[tuple[str, str | None]] = []

    def fake_clone(url: str, dest: Path, ref: str | None) -> None:
        cloned.append((url, ref))
        write_plugin(dest, name="from-git", version="9.9.9")

    record = install_plugin(
        "acme/tools@v1",
        assume_yes=True,
        home=home,
        clone=fake_clone,
    )
    assert cloned == [("https://github.com/acme/tools.git", "v1")]
    assert record.name == "from-git"
    assert record.version == "9.9.9"
    saved = json.loads((home / "plugins" / "registry.json").read_text(encoding="utf-8"))
    assert saved["plugins"][0]["source"] == "acme/tools@v1"


def test_redact_git_userinfo() -> None:
    assert "s3cret" not in redact_secrets("failed https://git:s3cret@example.com/a.git")
