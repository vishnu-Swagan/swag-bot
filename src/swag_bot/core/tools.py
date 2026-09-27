"""Built-in tools for a v0 run: read a file, write a file, run a shell command.

Every path and command goes through the injected ``Sandbox``. The sandbox
rejects paths that leave its workdir. The CLI points that workdir at the
output directory when the safety package has not installed its own sandbox.
"""

from __future__ import annotations

from collections.abc import Callable

from swag_bot.errors import SandboxError
from swag_bot.interfaces import Sandbox, Tool, ToolRegistry

READ_FILE = Tool(
    name="read_file",
    description="Read a UTF-8 text file. The path is relative to the sandbox workdir.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path inside the workdir."},
        },
        "required": ["path"],
    },
)

WRITE_FILE = Tool(
    name="write_file",
    description=(
        "Write a UTF-8 text file inside the sandbox workdir. Parent directories are created."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path inside the workdir."},
            "content": {"type": "string", "description": "File text."},
        },
        "required": ["path", "content"],
    },
)

RUN_SHELL = Tool(
    name="run_shell",
    description=(
        "Run a shell command in the sandbox workdir and return exit code, stdout, and stderr."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command."},
            "timeout": {
                "type": "number",
                "description": "Optional timeout in seconds. A timeout exits 124.",
            },
        },
        "required": ["command"],
    },
)

BUILTIN_TOOLS = (READ_FILE, WRITE_FILE, RUN_SHELL)


def register_builtin_tools(registry: ToolRegistry, sandbox: Sandbox) -> None:
    """Register the built-in tools. An existing name is left in place.

    Callers that want a different handler for ``read_file`` can register it
    before calling this function.
    """
    present = {tool.name for tool in registry.list_tools()}
    handlers = {
        READ_FILE.name: _read(sandbox),
        WRITE_FILE.name: _write(sandbox),
        RUN_SHELL.name: _shell(sandbox),
    }
    for tool in BUILTIN_TOOLS:
        if tool.name in present:
            continue
        registry.register(tool, handlers[tool.name])


def _read(sandbox: Sandbox) -> Callable[..., str]:
    def read_file(path: str) -> str:
        try:
            return sandbox.read_file(path)
        except (SandboxError, FileNotFoundError, OSError) as exc:
            return f"error: {exc}"

    return read_file


def _write(sandbox: Sandbox) -> Callable[..., str]:
    def write_file(path: str, content: str) -> str:
        try:
            sandbox.write_file(path, content)
        except (SandboxError, OSError) as exc:
            return f"error: {exc}"
        return f"wrote {path}"

    return write_file


def _shell(sandbox: Sandbox) -> Callable[..., str]:
    def run_shell(command: str, timeout: float | None = None) -> str:
        try:
            result = sandbox.run(command, timeout=timeout)
        except (SandboxError, OSError) as exc:
            return f"error: {exc}"
        return (
            f"exit_code={result.exit_code} timed_out={str(result.timed_out).lower()}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    return run_shell
