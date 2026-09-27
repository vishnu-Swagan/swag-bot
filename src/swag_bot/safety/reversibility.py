"""Classify an action as reversible, compensable, or irreversible.

Workspace writes and shell commands that stay inside the sandbox are
reversible, because the undo ledger snapshots that directory before they
run. Network calls, mail, payments, publishes, and writes outside that
directory are irreversible unless a compensation handler is registered.

Shell classification is a heuristic. It looks for commands and paths that
usually leave the machine. It will miss a Python one-liner that opens an
absolute path, and it will flag some commands that would have failed.
The snapshot still runs first, so in-workdir damage from a mixed command
can be restored even when the command is marked irreversible.
"""

from __future__ import annotations

import re
from pathlib import Path

from swag_bot.errors import SandboxError
from swag_bot.interfaces import ActionRequest, Reversibility, RiskLevel, resolve_sandbox_path
from swag_bot.safety.compensation import CompensationRegistry

_READ_KINDS = {"read_file", "list_dir", "memory", "search"}
_WRITE_KINDS = {"write_file", "edit_file", "create_file"}
_DELETE_KINDS = {"delete", "unlink"}
_SHELL_KINDS = {"run_command", "shell", "exec", "bash"}
_SHELL_TOOLS = {"run_shell", "shell", "bash", "exec"}
_EXTERNAL_KINDS = {
    "network",
    "http",
    "fetch",
    "send_message",
    "message",
    "email",
    "spend",
    "payment",
    "purchase",
    "billing",
}

_NETWORK = re.compile(
    r"(?i)\b(?:curl|wget|ssh|scp|sftp|nc|ncat|ftp|telnet|sendmail|mailx|pip3?\s+install)\b|https?://"
)
_PUBLISH = re.compile(
    r"(?i)\b(?:git\s+push|npm\s+publish|pnpm\s+publish|yarn\s+publish|"
    r"docker\s+push|twine\s+upload|cargo\s+publish)\b"
)
_SEND = re.compile(
    r"(?i)\b(?:send(?:ing)?\s+(?:a\s+)?(?:message|email|mail)|post\s+to\s+slack)\b"
)
_SPEND = re.compile(r"(?i)\b(?:spend(?:ing)?\s+money|purchase|payment|credit card|billing)\b")
_REDIRECT_OUTSIDE = re.compile(r"(?:^|[^>])>>?\s*/(?!dev/null\b)")
_MUTATION = re.compile(
    r"(?i)(?:^|[;&|`(])\s*(?:sudo\s+)?"
    r"(?:rm|rmdir|unlink|mv|cp|install|dd|truncate|tee|chmod|chown|ln|mkdir|touch|shred)\b"
    r"([^;&|]*)"
)
_ABSOLUTE = re.compile(r"(?:^|\s)/(?!dev/null\b)\S+")


def classify_reversibility(
    action: ActionRequest,
    *,
    compensations: CompensationRegistry | None = None,
    workdir: Path | None = None,
) -> Reversibility:
    """Return how ``action`` can be undone.

    A registered handler turns an otherwise irreversible action into
    ``compensable``. A handler is not required for workspace edits: the
    snapshot covers those.
    """
    if action.reversibility is not None:
        return action.reversibility
    base = _from_shape(action, workdir=workdir)
    if base is not Reversibility.IRREVERSIBLE:
        return base
    tool = _tool_name(action)
    if compensations is not None and tool and compensations.has_handler(tool):
        return Reversibility.COMPENSABLE
    return Reversibility.IRREVERSIBLE


def command_is_irreversible(command: str) -> bool:
    """True when ``command`` likely does something a workspace snapshot cannot undo."""
    if _NETWORK.search(command) or _PUBLISH.search(command):
        return True
    if _SEND.search(command) or _SPEND.search(command):
        return True
    if _REDIRECT_OUTSIDE.search(command):
        return True
    for match in _MUTATION.finditer(command):
        if _ABSOLUTE.search(match.group(1)):
            return True
    return False


def _from_shape(action: ActionRequest, *, workdir: Path | None) -> Reversibility:
    kind = action.kind
    tool = _tool_name(action)
    if action.risk is RiskLevel.READ or kind in _READ_KINDS:
        return Reversibility.REVERSIBLE
    if kind in _WRITE_KINDS or kind in _DELETE_KINDS:
        if _path_escapes(_file_target(action), workdir):
            return Reversibility.IRREVERSIBLE
        return Reversibility.REVERSIBLE
    if kind in _SHELL_KINDS or (tool or "") in _SHELL_TOOLS:
        command = _command_text(action)
        if not command:
            return Reversibility.IRREVERSIBLE
        if command_is_irreversible(command):
            return Reversibility.IRREVERSIBLE
        return Reversibility.REVERSIBLE
    if kind in _EXTERNAL_KINDS:
        return Reversibility.IRREVERSIBLE
    return Reversibility.IRREVERSIBLE


def _tool_name(action: ActionRequest) -> str:
    if action.tool_name:
        return action.tool_name
    return action.kind


def _command_text(action: ActionRequest) -> str:
    if action.target and action.kind in _SHELL_KINDS.union(_SHELL_TOOLS):
        return action.target
    if action.tool_name in _SHELL_TOOLS and action.target:
        return action.target
    command = action.arguments.get("command")
    if isinstance(command, str):
        return command
    if action.kind in _SHELL_KINDS and action.target:
        return action.target
    return ""


def _file_target(action: ActionRequest) -> str | None:
    if action.target:
        return action.target
    path = action.arguments.get("path")
    if isinstance(path, str):
        return path
    return None


def _path_escapes(target: str | None, workdir: Path | None) -> bool:
    if not target:
        return False
    path = Path(target)
    if path.is_absolute() or ".." in path.parts:
        return True
    if workdir is None:
        return False
    try:
        resolve_sandbox_path(workdir, target)
    except SandboxError:
        return True
    return False
