"""A real stdio MCP client must survive ``swag serve-mcp`` approvals.

The server process is the production ``swag serve-mcp`` command with a
scripted model. Stdout is the protocol channel. A terminal yes/no prompt
would hang this client or make the handshake fail.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("anyio")

import anyio
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import ElicitResult

from mcp import ClientSession

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve().parent / "fake_stdio_main.py"
ElicitCallback = Callable[..., Awaitable[ElicitResult]]


def _text(result: object) -> str:
    chunks: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)


async def _call(
    mode: str,
    work: Path,
    home: Path,
    callback: ElicitCallback | None,
) -> tuple[str, str]:
    err_path = work / "stderr.txt"
    env = {
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "src"))),
        "SWAG_HOME": str(home),
        "SWAG_STDIO_FIXTURE": mode,
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "NO_COLOR": "1",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SCRIPT)],
        env=env,
        cwd=str(work),
    )
    try:
        with err_path.open("w", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write, elicitation_callback=callback) as session:
                    with anyio.fail_after(30):
                        await session.initialize()
                        result = await session.call_tool(
                            "swag_run_task",
                            {"goal": "write hello.txt"},
                        )
        return _text(result), err_path.read_text(encoding="utf-8")
    except Exception as exc:
        err = err_path.read_text(encoding="utf-8") if err_path.is_file() else ""
        raise AssertionError(f"{exc}\n--- stderr ---\n{err[-4000:]}") from exc


def _run(
    mode: str,
    tmp_path: Path,
    callback: ElicitCallback | None = None,
) -> tuple[str, str, Path]:
    work = tmp_path / "work"
    home = tmp_path / "home"
    work.mkdir()
    home.mkdir()
    text, err = anyio.run(_call, mode, work, home, callback)
    return text, err, work


def _assert_protocol_clean(err: str) -> None:
    assert "TERMINAL_PROMPTER" not in err
    assert "Allow this action?" not in err
    assert "Approval required" not in err


def test_client_without_elicitation_is_denied_and_the_session_stays_valid(tmp_path: Path) -> None:
    text, err, work = _run("deny", tmp_path)
    _assert_protocol_clean(err)
    assert "Denied" in text
    assert "elicitation" in text
    assert list(work.rglob("hello.txt")) == []


def test_accepted_elicitation_writes_the_file(tmp_path: Path) -> None:
    seen: list[str] = []

    async def accept(_context: object, params: object) -> ElicitResult:
        seen.append(str(getattr(params, "message", "")))
        return ElicitResult(action="accept", content={"allow": True})

    text, err, work = _run("allow", tmp_path, accept)
    _assert_protocol_clean(err)
    assert seen, text
    files = list(work.rglob("hello.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "hello\n"
    assert "Wrote hello.txt." in text


def test_declined_elicitation_does_not_write(tmp_path: Path) -> None:
    async def decline(_context: object, _params: object) -> ElicitResult:
        return ElicitResult(action="decline")

    text, err, work = _run("deny", tmp_path, decline)
    _assert_protocol_clean(err)
    assert "declined" in text.lower()
    assert list(work.rglob("hello.txt")) == []


def test_preapproved_write_does_not_elicit(tmp_path: Path) -> None:
    work = tmp_path / "work"
    home = tmp_path / "home"
    work.mkdir()
    home.mkdir()
    (home / "mcp-approvals.json").write_text(
        json.dumps({"risks": ["write"], "kinds": []}) + "\n",
        encoding="utf-8",
    )
    # No elicitation callback: the client does not advertise the capability.
    # A form request would be an error from the default callback and fail the call.
    text, err = anyio.run(_call, "allow", work, home, None)
    _assert_protocol_clean(err)
    files = list(work.rglob("hello.txt"))
    assert len(files) == 1, text
    assert files[0].read_text(encoding="utf-8") == "hello\n"
