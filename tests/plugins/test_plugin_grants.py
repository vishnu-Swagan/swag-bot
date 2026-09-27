"""Install approval persists grants; decline, disable, and remove do not leave them active."""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swag_bot.cli import app
from swag_bot.interfaces import ActionRequest, AutonomyLevel, RiskLevel
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.installer import install_plugin
from swag_bot.safety.policy import (
    DefaultPermissionPolicy,
    PolicyDecision,
    grants_path,
    load_grants,
    load_suspended_grants,
)
from tests.cli_output import visible as _visible
from tests.fakes import AutoApprovePrompter
from tests.plugins.helpers import write_plugin

runner = CliRunner()
PLUGIN = "demo-plugin"
PERMISSIONS = ["filesystem.read", "network"]


class DenyPrompter:
    def prompt(self, action: ActionRequest) -> bool:
        del action
        return False


class RecordingStore:
    def __init__(self) -> None:
        self.events: list[str] = []

    def replace(self, plugin: str, permissions: Sequence[str], *, active: bool = True) -> None:
        self.events.append(f"replace:{plugin}:{active}:{','.join(permissions)}")

    def suspend(self, plugin: str) -> None:
        self.events.append(f"suspend:{plugin}")

    def resume(self, plugin: str) -> None:
        self.events.append(f"resume:{plugin}")

    def revoke(self, plugin: str) -> None:
        self.events.append(f"revoke:{plugin}")


def _source(tmp_path: Path, *, default_enabled: bool = True) -> Path:
    return write_plugin(
        tmp_path / "src",
        name=PLUGIN,
        permissions=list(PERMISSIONS),
        default_enabled=default_enabled,
    )


def _tagged(kind: str, *, risk: RiskLevel = RiskLevel.READ) -> ActionRequest:
    return ActionRequest(
        kind=kind,
        summary=kind,
        risk=risk,
        arguments={"plugin": PLUGIN},
    )


def _auto_policy() -> DefaultPermissionPolicy:
    return DefaultPermissionPolicy(AutonomyLevel.AUTO, grants=load_grants())


def test_yes_persists_grants_without_lowering_denies(tmp_path: Path) -> None:
    source = _source(tmp_path)
    installed = runner.invoke(app, ["plugin", "install", str(source), "--yes"])
    assert installed.exit_code == 0
    assert "filesystem.read" in _visible(installed)

    document = json.loads(grants_path().read_text(encoding="utf-8"))
    assert document["plugins"][PLUGIN] == ["filesystem.read", "network"]
    assert "suspended" not in document

    policy = _auto_policy()
    read = _tagged("read_file")
    write = _tagged("write_file", risk=RiskLevel.WRITE)
    destructive = _tagged("write_file", risk=RiskLevel.DESTRUCTIVE)
    assert policy.decide(read) is PolicyDecision.ALLOW
    assert policy.is_denied(write) is True
    assert policy.decide(write) is PolicyDecision.DENY
    assert policy.requires_approval(write) is False
    assert policy.classify(destructive) is RiskLevel.DESTRUCTIVE
    assert policy.decide(destructive) is PolicyDecision.DENY

    risky = DefaultPermissionPolicy(AutonomyLevel.ASK_RISKY, grants=load_grants())
    network = _tagged("network", risk=RiskLevel.NETWORK)
    assert risky.is_denied(network) is False
    assert risky.decide(network) is PolicyDecision.PROMPT
    assert risky.classify(destructive) is RiskLevel.DESTRUCTIVE


def test_prompt_approval_persists_the_same_grants(tmp_path: Path) -> None:
    source = _source(tmp_path)
    approved = runner.invoke(app, ["plugin", "install", str(source)], input="y\n")
    assert approved.exit_code == 0
    assert load_grants()[PLUGIN] == {"filesystem.read", "network"}


def test_declined_install_writes_no_grants(tmp_path: Path) -> None:
    source = _source(tmp_path)
    denied = runner.invoke(app, ["plugin", "install", str(source)], input="n\n")
    assert denied.exit_code == 1
    assert "installation denied" in _visible(denied)
    assert not grants_path().exists()
    assert not (Path(grants_path()).parent / "plugins" / PLUGIN).exists()
    assert load_grants() == {}


def test_declined_install_does_not_call_the_store(tmp_path: Path) -> None:
    source = _source(tmp_path)
    home = tmp_path / "custom-home"
    store = RecordingStore()
    with pytest.raises(PluginError, match="installation denied"):
        install_plugin(str(source), prompter=DenyPrompter(), home=home, grant_store=store)
    assert store.events == []
    assert not grants_path().exists()
    assert not (home / "grants.json").exists()


def test_custom_home_does_not_touch_process_grants(tmp_path: Path) -> None:
    source = _source(tmp_path)
    install_plugin(str(source), assume_yes=True, home=tmp_path / "custom-home")
    assert not grants_path().exists()


def test_disable_denies_until_enable_and_remove_revokes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    assert runner.invoke(app, ["plugin", "install", str(source), "--yes"]).exit_code == 0
    assert runner.invoke(app, ["safety", "grant", "other", "shell"]).exit_code == 0

    disabled = runner.invoke(app, ["plugin", "disable", PLUGIN])
    assert disabled.exit_code == 0
    assert PLUGIN not in load_grants()
    assert load_suspended_grants()[PLUGIN] == {"filesystem.read", "network"}
    assert load_grants()["other"] == {"shell"}
    assert _auto_policy().decide(_tagged("read_file")) is PolicyDecision.DENY

    extra = runner.invoke(app, ["safety", "grant", PLUGIN, "filesystem.write"])
    assert extra.exit_code == 0
    assert PLUGIN not in load_grants()
    assert load_suspended_grants()[PLUGIN] == {"filesystem.read", "filesystem.write", "network"}
    denied = _auto_policy()
    destructive = _tagged("write_file", risk=RiskLevel.DESTRUCTIVE)
    assert denied.decide(destructive) is PolicyDecision.DENY
    assert denied.classify(destructive) is RiskLevel.DESTRUCTIVE

    enabled = runner.invoke(app, ["plugin", "enable", PLUGIN])
    assert enabled.exit_code == 0
    assert load_grants()[PLUGIN] == {"filesystem.read", "filesystem.write", "network"}
    assert PLUGIN not in load_suspended_grants()
    assert _auto_policy().decide(_tagged("read_file")) is PolicyDecision.ALLOW
    assert _auto_policy().decide(_tagged("write_file")) is PolicyDecision.ALLOW

    removed = runner.invoke(app, ["plugin", "remove", PLUGIN])
    assert removed.exit_code == 0
    assert PLUGIN not in load_grants()
    assert PLUGIN not in load_suspended_grants()
    assert load_grants()["other"] == {"shell"}
    assert _auto_policy().decide(_tagged("read_file")) is PolicyDecision.DENY


def test_default_disabled_install_stays_denied_until_enable(tmp_path: Path) -> None:
    source = _source(tmp_path, default_enabled=False)
    installed = runner.invoke(app, ["plugin", "install", str(source), "--yes"])
    assert installed.exit_code == 0
    assert PLUGIN not in load_grants()
    assert load_suspended_grants()[PLUGIN] == {"filesystem.read", "network"}
    assert _auto_policy().decide(_tagged("read_file")) is PolicyDecision.DENY

    assert runner.invoke(app, ["plugin", "enable", PLUGIN]).exit_code == 0
    assert load_grants()[PLUGIN] == {"filesystem.read", "network"}
    assert _auto_policy().decide(_tagged("read_file")) is PolicyDecision.ALLOW


def test_plugins_package_does_not_import_safety() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "swag_bot" / "plugins"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module == "swag_bot.safety" or module.startswith("swag_bot.safety."):
                    offenders.append(f"{path.name}: {module}")
    assert offenders == []


def test_approved_install_can_use_an_explicit_store(tmp_path: Path) -> None:
    source = _source(tmp_path)
    home = tmp_path / "custom-home"
    store = RecordingStore()
    record = install_plugin(
        str(source),
        prompter=AutoApprovePrompter(),
        home=home,
        grant_store=store,
    )
    assert record.permissions == PERMISSIONS
    assert store.events == [f"replace:{PLUGIN}:True:filesystem.read,network"]
    assert not grants_path().exists()
