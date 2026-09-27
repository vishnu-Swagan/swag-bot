"""Local and Docker sandboxes.

``LocalSandbox`` is a restricted subprocess in one workdir. ``DockerSandbox``
runs the same command in a throwaway container. ``build_sandbox`` selects
from ``settings.sandbox.mode`` and falls back to the local sandbox, with a
warning, when Docker is missing.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from swag_bot.config import SandboxMode, Settings
from swag_bot.errors import SandboxError
from swag_bot.interfaces import TIMEOUT_EXIT_CODE, CommandResult, resolve_sandbox_path

DEFAULT_MEMORY = "512m"
DEFAULT_CPUS = "1"
DEFAULT_PIDS = "256"

DOCKER_FALLBACK_WARNING = (
    "Docker is not available. Falling back to the local sandbox: "
    "commands run in a temp workdir with timeouts and path checks, not a container."
)

_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSWD)", re.IGNORECASE)

_KEEP_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "TERM",
    "USER",
    "LOGNAME",
    "SHELL",
)


def docker_backend() -> str | None:
    """``cli`` when the docker binary is on PATH, ``sdk`` when only the library is, else None."""
    if shutil.which("docker"):
        return "cli"
    if importlib.util.find_spec("docker") is not None:
        return "sdk"
    return None


def restricted_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for a local command. API keys and other secrets are left out."""
    base = os.environ if source is None else source
    env: dict[str, str] = {}
    for key in _KEEP_ENV:
        value = base.get(key)
        if value is None or _SECRET_ENV.search(key):
            continue
        env[key] = value
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def execute_command(
    command: str,
    argv: Sequence[str] | str,
    *,
    timeout: float | None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    shell: bool = False,
) -> CommandResult:
    """Run ``argv`` and return a ``CommandResult``. Timeouts do not raise.

    A timeout kills the process group and returns exit code 124
    (``TIMEOUT_EXIT_CODE``) with ``timed_out=True``.
    """
    popen_cmd: str | Sequence[str] = command if shell else list(argv)
    proc = subprocess.Popen(
        popen_cmd,
        shell=shell,
        cwd=str(cwd) if cwd is not None else None,
        env=None if env is None else dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        executable="/bin/sh" if shell else None,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        return CommandResult(
            command=command,
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=True,
        )
    return CommandResult(
        command=command,
        exit_code=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout or "",
        stderr=stderr or "",
        timed_out=False,
    )


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    proc.kill()


class _WorkdirFiles:
    """File helpers shared by every sandbox. Paths go through ``resolve_sandbox_path``."""

    def __init__(self, workdir: Path) -> None:
        self._workdir = Path(workdir)
        self._workdir.mkdir(parents=True, exist_ok=True)

    @property
    def workdir(self) -> Path:
        return self._workdir

    def read_file(self, path: str) -> str:
        target = resolve_sandbox_path(self._workdir, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        target = resolve_sandbox_path(self._workdir, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class LocalSandbox(_WorkdirFiles):
    """Restricted subprocess sandbox.

    Commands run with ``cwd`` set to the workdir, a secret-stripped
    environment, and an optional timeout. File reads and writes cannot leave
    the workdir. This is the fallback when Docker is missing; it is not a
    container.
    """

    def __init__(self, workdir: Path | None = None) -> None:
        self._owned: tempfile.TemporaryDirectory[str] | None = None
        if workdir is None:
            self._owned = tempfile.TemporaryDirectory(prefix="swag-sandbox-")
            root = Path(self._owned.name)
        else:
            root = Path(workdir)
        super().__init__(root)

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        return execute_command(
            command,
            command,
            timeout=timeout,
            cwd=self._workdir,
            env=restricted_env(),
            shell=True,
        )


class DisabledSandbox(_WorkdirFiles):
    """``sandbox.mode = off``. File helpers still work. ``run`` is refused."""

    def __init__(self, workdir: Path | None = None) -> None:
        root, self._owned = _allocate(workdir)
        super().__init__(root)

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        raise SandboxError("sandbox mode is off; commands are refused")


class DockerSandbox(_WorkdirFiles):
    """Throwaway container with the workdir mounted at ``/work``.

    Network is off unless ``network`` is true. CPU, memory, and pid limits
    are always set. ``timeout`` is enforced on the ``docker`` invocation
    (or the Docker SDK call) and reported as exit code 124.
    """

    def __init__(
        self,
        workdir: Path | None = None,
        *,
        image: str = "python:3.12-slim",
        network: bool = False,
        memory: str = DEFAULT_MEMORY,
        cpus: str = DEFAULT_CPUS,
        pids: str = DEFAULT_PIDS,
        backend: str | None = None,
    ) -> None:
        root, self._owned = _allocate(workdir)
        super().__init__(root)
        self.image = image
        self.network = network
        self.memory = memory
        self.cpus = cpus
        self.pids = pids
        self.backend = backend if backend is not None else (docker_backend() or "cli")

    def command_argv(self, command: str) -> list[str]:
        """``docker run`` arguments for ``command``. Does not execute anything."""
        workdir = str(self._workdir.resolve())
        argv = [
            "docker",
            "run",
            "--rm",
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--pids-limit",
            self.pids,
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m",
            "-v",
            f"{workdir}:/work:rw",
            "-w",
            "/work",
        ]
        if not self.network:
            argv.append("--network=none")
        argv.extend([self.image, "sh", "-c", command])
        return argv

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        if self.backend == "sdk":
            return self._run_sdk(command, timeout=timeout)
        return execute_command(
            command,
            self.command_argv(command),
            timeout=timeout,
            cwd=None,
            env=None,
            shell=False,
        )

    def _run_sdk(self, command: str, *, timeout: float | None) -> CommandResult:
        try:
            docker_sdk: Any = importlib.import_module("docker")
        except ImportError as exc:
            raise SandboxError(
                "Docker SDK is not installed. Install it with: pip install 'swag-bot[sandbox]'"
            ) from exc
        client = docker_sdk.from_env()
        kwargs: dict[str, object] = {
            "image": self.image,
            "command": ["sh", "-c", command],
            "detach": True,
            "remove": False,
            "volumes": {str(self._workdir.resolve()): {"bind": "/work", "mode": "rw"}},
            "working_dir": "/work",
            "mem_limit": self.memory,
            "nano_cpus": int(float(self.cpus) * 1_000_000_000),
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "read_only": True,
            "tmpfs": {"/tmp": "rw,nosuid,size=64m"},
            "pids_limit": int(self.pids),
        }
        if not self.network:
            kwargs["network_mode"] = "none"
        container = client.containers.run(**kwargs)
        try:
            if timeout is None:
                status = container.wait()
            else:
                status = container.wait(timeout=timeout)
            stdout = _logs(container, stdout=True)
            stderr = _logs(container, stdout=False)
            code = int(status.get("StatusCode", 1)) if isinstance(status, dict) else 1
            return CommandResult(command=command, exit_code=code, stdout=stdout, stderr=stderr)
        except Exception as exc:
            timed_out = exc.__class__.__name__ in {"ReadTimeout", "ConnectionError"} or (
                "timeout" in str(exc).lower()
            )
            try:
                container.kill()
            except Exception:
                pass
            if timed_out:
                return CommandResult(
                    command=command,
                    exit_code=TIMEOUT_EXIT_CODE,
                    stdout="",
                    stderr=str(exc),
                    timed_out=True,
                )
            return CommandResult(command=command, exit_code=1, stdout="", stderr=str(exc))
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass


def _logs(container: object, *, stdout: bool) -> str:
    logs = getattr(container, "logs", None)
    if logs is None:
        return ""
    raw = logs(stdout=stdout, stderr=not stdout)
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw or "")


def warn_docker_fallback() -> None:
    """Tell the operator that commands will not be containerized."""
    warnings.warn(DOCKER_FALLBACK_WARNING, RuntimeWarning, stacklevel=3)
    print(f"warning: {DOCKER_FALLBACK_WARNING}", file=sys.stderr)


def _allocate(workdir: Path | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if workdir is not None:
        return Path(workdir), None
    owned = tempfile.TemporaryDirectory(prefix="swag-sandbox-")
    return Path(owned.name), owned


def make_sandbox(
    settings: Settings, workdir: Path | None = None
) -> LocalSandbox | DockerSandbox | DisabledSandbox:
    """Build the sandbox selected by ``settings.sandbox.mode``."""
    mode = settings.sandbox.mode
    if mode is SandboxMode.OFF:
        return DisabledSandbox(workdir)
    if mode is SandboxMode.DOCKER:
        if docker_backend() is None:
            warn_docker_fallback()
            return LocalSandbox(workdir)
        return DockerSandbox(
            workdir,
            image=settings.sandbox.image,
            network=settings.sandbox.network,
        )
    return LocalSandbox(workdir)
