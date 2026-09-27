"""``scripts/install.sh --dry-run`` prints the plan and does not install anything."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dry_run_prints_uv_and_setup_without_running_them(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        ["sh", "scripts/install.sh", "--dry-run", "--", "run", "hello"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "would run: curl -LsSf https://astral.sh/uv/install.sh | sh" in output
    assert "uv tool install" in output
    assert "swag-bot[mcp,models] @ git+https://github.com/vishnu-Swagan/swag-bot" in output
    assert "swag setup --auto" in output
    assert "docs/MODELS.md" in output
    assert "swag run hello" in output
    assert "API_KEY" not in output
    syntax = subprocess.run(
        ["sh", "-n", "scripts/install.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_swag_ref_is_appended_to_the_git_url(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = str(tmp_path)
    env["SWAG_REF"] = "v0.2.0"
    result = subprocess.run(
        ["sh", "scripts/install.sh", "--dry-run", "--", "run", "hello"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "git+https://github.com/vishnu-Swagan/swag-bot@v0.2.0" in result.stdout
    assert "export PATH=" in result.stdout
    assert "uv tool update-shell" in result.stdout
