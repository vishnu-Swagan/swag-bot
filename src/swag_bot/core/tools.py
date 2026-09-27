"""Built-in tools for a v0 run: read a file, write a file, run a shell command.

Every path and command goes through the injected ``Sandbox``. The sandbox
rejects paths that leave its workdir. The CLI points that workdir at the
output directory when the safety package has not installed its own sandbox.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path

from swag_bot.errors import SandboxError
from swag_bot.interfaces import Sandbox, Tool, ToolRegistry

_CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyw",
        ".sh",
        ".bash",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".php",
        ".swift",
        ".kt",
    }
)
_BARE_PYTHON = re.compile(r"(^|[;&|]\s*|(?:&&|\|\|)\s*)python(?=\s|$)")

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
    note = python_interpreter_note()
    shell = RUN_SHELL.model_copy(
        update={"description": f"{RUN_SHELL.description} {note}"}
    )
    specs = {READ_FILE.name: READ_FILE, WRITE_FILE.name: WRITE_FILE, RUN_SHELL.name: shell}
    for tool in BUILTIN_TOOLS:
        if tool.name in present:
            continue
        registry.register(specs[tool.name], handlers[tool.name])


def _read(sandbox: Sandbox) -> Callable[..., str]:
    def read_file(path: str) -> str:
        try:
            return sandbox.read_file(path)
        except (SandboxError, FileNotFoundError, OSError) as exc:
            return f"error: {exc}"

    return read_file


def normalize_written_text(path: str, content: str) -> str:
    """Turn a one-line escaped source file into real newlines, and end with one.

    Models sometimes send ``for i in range(1, 101):\\n    print(i)`` as a
    single line. That is a ``SyntaxError`` when Python reads it. Only a
    single-line code file that contains literal backslash-n sequences is
    unescaped. Every non-empty text file ends with a newline.
    """
    suffix = Path(path).suffix.lower()
    if suffix in _CODE_SUFFIXES and "\n" not in content and "\\n" in content:
        content = content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    if content and not content.endswith("\n"):
        content += "\n"
    return content


def python_interpreter_note(
    *,
    which: Callable[[str], str | None] | None = None,
) -> str:
    """Tell the model which Python command exists in this environment."""
    finder = which or shutil.which
    has_python3 = finder("python3") is not None
    has_python = finder("python") is not None
    if has_python3 and not has_python:
        return (
            "Python: `python3` is on PATH and `python` is not. "
            "Run scripts with python3. Do not install Python from a website."
        )
    if has_python and not has_python3:
        return "Python: `python` is on PATH and `python3` is not. Run scripts with python."
    if has_python3 and has_python:
        return "Python: `python3` and `python` are both on PATH. Prefer python3."
    return "Python: neither `python` nor `python3` is on PATH."


def rewrite_python_command(
    command: str,
    *,
    which: Callable[[str], str | None] | None = None,
) -> str:
    """Replace a bare ``python`` with ``python3`` when ``python`` is missing."""
    finder = which or shutil.which
    if finder("python") is not None or finder("python3") is None:
        return command
    return _BARE_PYTHON.sub(r"\1python3", command)


def _write(sandbox: Sandbox) -> Callable[..., str]:
    def write_file(path: str, content: str) -> str:
        text = normalize_written_text(path, content)
        try:
            sandbox.write_file(path, text)
        except (SandboxError, OSError) as exc:
            return f"error: {exc}"
        return f"wrote {path}"

    return write_file


def _shell(sandbox: Sandbox) -> Callable[..., str]:
    def run_shell(command: str, timeout: float | None = None) -> str:
        command = rewrite_python_command(command)
        try:
            result = sandbox.run(command, timeout=timeout)
        except (SandboxError, OSError) as exc:
            return f"error: {exc}"
        return (
            f"exit_code={result.exit_code} timed_out={str(result.timed_out).lower()}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    return run_shell
