"""The PyPI switch stays one constant, repeated in the install scripts."""

from __future__ import annotations

from pathlib import Path

from swag_bot.onboarding.distribution import (
    GIT_INSTALL_URL,
    PYPI_PUBLISHED,
    requirement,
    uv_tool_install_spec,
    uvx_serve_args,
)

ROOT = Path(__file__).resolve().parents[2]


def test_scripts_repeat_the_python_constant() -> None:
    shell = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    flag = "1" if PYPI_PUBLISHED else "0"
    assert f'GIT_INSTALL_URL="{GIT_INSTALL_URL}"' in shell
    assert f"PYPI_PUBLISHED={flag}" in shell
    assert f'$GitInstallUrl = "{GIT_INSTALL_URL}"' in powershell
    assert f"$PypiPublished = {flag}" in powershell


def test_requirement_uses_git_until_pypi_exists() -> None:
    spec = requirement("mcp")
    if PYPI_PUBLISHED:
        assert spec == "swag-bot[mcp]"
    else:
        assert spec == f"swag-bot[mcp] @ {GIT_INSTALL_URL}"
    assert uv_tool_install_spec() == requirement("mcp,models")
    assert uvx_serve_args()[:2] == ["--from", requirement("mcp")]
    assert uvx_serve_args()[-2:] == ["swag-bot", "serve-mcp"]
