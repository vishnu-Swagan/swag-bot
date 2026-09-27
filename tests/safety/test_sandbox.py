"""Local sandbox path checks, timeouts, and the Docker fallback."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from swag_bot.config import SandboxMode, SandboxSettings, Settings
from swag_bot.errors import SandboxError
from swag_bot.interfaces import TIMEOUT_EXIT_CODE
from swag_bot.safety import build_sandbox
from swag_bot.safety.sandbox import DockerSandbox, LocalSandbox


def test_local_roundtrip_and_cwd(tmp_path: Path) -> None:
    sandbox = LocalSandbox(tmp_path)
    sandbox.write_file("notes/a.txt", "hello")
    assert sandbox.read_file("notes/a.txt") == "hello"
    result = sandbox.run("pwd")
    assert result.exit_code == 0
    assert result.timed_out is False
    assert Path(result.stdout.strip()).resolve() == sandbox.workdir.resolve()


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    sandbox = LocalSandbox(tmp_path / "work")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(SandboxError):
        sandbox.write_file("../secret.txt", "x")
    with pytest.raises(SandboxError):
        sandbox.write_file(str(outside), "x")
    with pytest.raises(SandboxError):
        sandbox.read_file("../secret.txt")
    link = sandbox.workdir / "link"
    link.symlink_to(outside)
    with pytest.raises(SandboxError):
        sandbox.read_file("link")
    assert outside.read_text(encoding="utf-8") == "nope"


def test_run_timeout_returns_124(tmp_path: Path) -> None:
    sandbox = LocalSandbox(tmp_path)
    result = sandbox.run("sleep 5", timeout=0.4)
    assert result.timed_out is True
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.command == "sleep 5"


def test_local_env_drops_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-testsecretvalue1234567890")
    sandbox = LocalSandbox(tmp_path)
    code = "import os; print(os.environ.get('OPENAI_API_KEY', ''))"
    result = sandbox.run(f"{sys.executable} -c {json.dumps(code)}")
    assert result.exit_code == 0
    assert "sk-testsecretvalue1234567890" not in result.stdout
    assert result.stdout.strip() == ""


def test_off_mode_refuses_run(tmp_path: Path) -> None:
    settings = Settings(sandbox=SandboxSettings(mode=SandboxMode.OFF))
    sandbox = build_sandbox(settings, workdir=tmp_path)
    sandbox.write_file("a.txt", "ok")
    assert sandbox.read_file("a.txt") == "ok"
    with pytest.raises(SandboxError, match="off"):
        sandbox.run("echo hi")


def test_docker_mode_falls_back_when_docker_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("swag_bot.safety.sandbox.docker_backend", lambda: None)
    settings = Settings(sandbox=SandboxSettings(mode=SandboxMode.DOCKER, network=False))
    with pytest.warns(RuntimeWarning, match="Docker is not available"):
        sandbox = build_sandbox(settings, workdir=tmp_path)
    assert isinstance(sandbox, LocalSandbox)


def test_docker_argv_limits_network_and_mount(tmp_path: Path) -> None:
    sandbox = DockerSandbox(
        tmp_path, image="python:3.12-slim", network=False, memory="256m", cpus="0.5"
    )
    argv = sandbox.command_argv("echo hi")
    assert argv[0] == "docker"
    assert "--network=none" in argv
    assert "--memory" in argv and "256m" in argv
    assert "--cpus" in argv and "0.5" in argv
    assert "--pids-limit" in argv
    assert "--cap-drop=ALL" in argv
    assert "--read-only" in argv
    mount = f"{tmp_path.resolve()}:/work:rw"
    assert mount in argv
    assert argv[-3:] == ["sh", "-c", "echo hi"]
    assert "python:3.12-slim" in argv

    networked = DockerSandbox(tmp_path, network=True)
    assert "--network=none" not in networked.command_argv("true")


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is not available")
def test_docker_echo_when_available(tmp_path: Path) -> None:
    sandbox = DockerSandbox(tmp_path, image="python:3.12-slim", network=False)
    result = sandbox.run("echo from-container", timeout=60)
    assert result.timed_out is False
    assert result.exit_code == 0
    assert "from-container" in result.stdout
