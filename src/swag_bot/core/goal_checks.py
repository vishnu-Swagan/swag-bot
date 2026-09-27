"""Goal-level acceptance checks derived from the words of the goal.

A step can pass its own checks while the goal is still unmet: the plan never
ran the script, the script printed the wrong text, or a verify step only
looked at the exit code. These checks are the run's acceptance test. The
harness runs them and records the evidence. A run is successful only when
every one of them passed and cited that evidence.
"""

from __future__ import annotations

import re
import shutil

from swag_bot.interfaces import Check

_FILENAME = re.compile(r"\b(?P<name>[\w./-]+\.(?:py|sh|bash|txt|md|json|csv))\b", re.IGNORECASE)
_RUN_WITH = re.compile(
    r"\b(?:run|execute)\b(?:[\w\s,'\"]{0,40}?)\bwith\s+(?P<prog>python3|python|node|bash|sh)\b",
    re.IGNORECASE,
)
_WANTS_RUN = re.compile(r"\b(?:run|execute)\b", re.IGNORECASE)
_WANTS_WRITE = re.compile(r"\b(?:write|create|save)\b", re.IGNORECASE)
_LAST_LINE = re.compile(
    r"\blast\s+line\b(?:\s+\w+){0,8}?\s+is\s+[\"']?(?P<text>[^\"'\n.]+)",
    re.IGNORECASE,
)
_ONE_PER_LINE = re.compile(
    r"\bone\s+per\s+line\b|\beach\s+on\s+(?:its|their)\s+own\s+line\b",
    re.IGNORECASE,
)
_RANGE = re.compile(
    r"\b(?:numbers?\s+)?(?P<start>\d+)\s+(?:to|through)\s+(?P<end>\d+)\b",
    re.IGNORECASE,
)


def derive_goal_checks(goal: str) -> list[Check]:
    """Machine checks for requirements the goal states explicitly.

    Examples: ``run it with python3`` becomes a command check, ``last line is
    FizzBuzz`` becomes an output check, and ``one per line`` with ``numbers 1
    to 15`` becomes a line-count check. A goal that does not state any of
    these returns an empty list.
    """
    text = goal.strip()
    if not text:
        return []
    files = _files(text)
    script = _script(files)
    run_with = _RUN_WITH.search(text)
    wants_run = run_with is not None or (script is not None and _WANTS_RUN.search(text) is not None)
    last_line = _last_line(text)
    line_count = _line_count(text)
    checks: list[Check] = []
    if (
        script is not None
        and _WANTS_WRITE.search(text) is not None
        and (wants_run or last_line is not None or line_count is not None)
    ):
        checks.append(
            Check(
                id="goal-file",
                kind="file_exists",
                path=script,
                description=f"{script} exists",
            )
        )
    command = ""
    if wants_run and script is not None:
        program = run_with.group("prog") if run_with is not None else _interpreter(script)
        command = f"{program} {script}"
        checks.append(
            Check(
                id="goal-run",
                kind="command",
                command=command,
                expected_exit=0,
                description=f"run {command}",
            )
        )
    if command and last_line is not None:
        checks.append(
            Check(
                id="goal-last-line",
                kind="stdout",
                command=command,
                stdout_last_line=last_line,
                description=f"last line is {last_line}",
            )
        )
    if command and line_count is not None:
        checks.append(
            Check(
                id="goal-lines",
                kind="stdout",
                command=command,
                stdout_line_count=line_count,
                description=f"output has {line_count} lines",
            )
        )
    return checks


def _files(goal: str) -> list[str]:
    found: list[str] = []
    for match in _FILENAME.finditer(goal):
        name = match.group("name")
        if name not in found:
            found.append(name)
    return found


def _script(files: list[str]) -> str | None:
    for name in files:
        if name.lower().endswith((".py", ".sh", ".bash")):
            return name
    if len(files) == 1:
        return files[0]
    return None


def _interpreter(script: str) -> str:
    if script.lower().endswith(".py"):
        if shutil.which("python3"):
            return "python3"
        if shutil.which("python"):
            return "python"
        return "python3"
    if script.lower().endswith((".sh", ".bash")):
        return "bash"
    return "python3"


def _last_line(goal: str) -> str | None:
    match = _LAST_LINE.search(goal)
    if match is None:
        return None
    text = match.group("text").strip().strip("\"'`")
    return text or None


def _line_count(goal: str) -> int | None:
    if _ONE_PER_LINE.search(goal) is None:
        return None
    match = _RANGE.search(goal)
    if match is None:
        return None
    start = int(match.group("start"))
    end = int(match.group("end"))
    if end < start:
        return None
    return end - start + 1
