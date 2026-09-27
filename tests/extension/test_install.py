"""Native host manifest paths for Linux, macOS, and Windows."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from swag_bot.errors import SwagError
from swag_bot.extension.ids import DEV_EXTENSION_ID, HOST_NAME
from swag_bot.extension.install import (
    browser_names,
    host_manifest,
    install_native_host,
    load_saved_ids,
    manifest_path,
    normalize_extension_id,
    registry_key,
    remove_native_host,
    status_lines,
)


class MemoryRegistry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set_value(self, key_path: str, value: str) -> None:
        self.values[key_path] = value

    def delete_key(self, key_path: str) -> None:
        self.values.pop(key_path, None)

    def read_value(self, key_path: str) -> str | None:
        return self.values.get(key_path)


def test_extension_id_must_be_32_a_to_p() -> None:
    assert normalize_extension_id(DEV_EXTENSION_ID.upper()) == DEV_EXTENSION_ID
    with pytest.raises(SwagError):
        normalize_extension_id("not-an-id")
    with pytest.raises(SwagError):
        normalize_extension_id("q" * 32)


def test_manifest_allows_only_named_extensions(tmp_path: Path) -> None:
    launcher = tmp_path / "swag-bot-host"
    payload = host_manifest(launcher, [DEV_EXTENSION_ID])
    assert payload["name"] == HOST_NAME
    assert payload["type"] == "stdio"
    assert payload["path"] == str(launcher)
    assert payload["allowed_origins"] == [f"chrome-extension://{DEV_EXTENSION_ID}/"]


def test_linux_paths_follow_xdg(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    path = manifest_path(
        os_home=home,
        swag_dir=tmp_path / "swag",
        platform="linux",
        environ={"XDG_CONFIG_HOME": str(xdg)},
        browser="chrome",
    )
    assert path == xdg / "google-chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    edge = manifest_path(
        os_home=home,
        swag_dir=tmp_path / "swag",
        platform="linux",
        environ={},
        browser="edge",
    )
    assert edge == (
        home / ".config" / "microsoft-edge" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    )


def test_macos_paths() -> None:
    home = Path("/Users/example")
    path = manifest_path(
        os_home=home,
        swag_dir=home / ".swag",
        platform="darwin",
        environ={},
        browser="chromium",
    )
    assert path == (
        home
        / "Library"
        / "Application Support"
        / "Chromium"
        / "NativeMessagingHosts"
        / f"{HOST_NAME}.json"
    )


def test_linux_install_writes_executable_host_and_three_manifests(tmp_path: Path) -> None:
    report = install_native_host(
        os_home=tmp_path / "home",
        swag_dir=tmp_path / "swag",
        platform="linux",
        environ={},
        extension_ids=["abcdefghijklmnopabcdefghijklmnop"],
        browsers=browser_names("all"),
        python_executable="/usr/bin/python3",
    )
    assert report.launcher.is_file()
    assert report.launcher.stat().st_mode & stat.S_IXUSR
    script = report.launcher.read_text(encoding="utf-8")
    assert "exec '/usr/bin/python3' -u -m swag_bot.extension.host" in script
    assert len(report.manifests) == 3
    saved = json.loads(report.manifests[0].read_text(encoding="utf-8"))
    origins = saved["allowed_origins"]
    assert f"chrome-extension://{DEV_EXTENSION_ID}/" in origins
    assert "chrome-extension://abcdefghijklmnopabcdefghijklmnop/" in origins
    assert load_saved_ids(tmp_path / "swag")[0] == DEV_EXTENSION_ID
    lines = status_lines(
        os_home=tmp_path / "home",
        swag_dir=tmp_path / "swag",
        platform="linux",
        environ={},
    )
    assert any(line.startswith("host: installed") for line in lines)
    assert any(line.startswith("chrome: present") for line in lines)


def test_remove_deletes_manifests_and_keeps_ids(tmp_path: Path) -> None:
    kwargs = {
        "os_home": tmp_path / "home",
        "swag_dir": tmp_path / "swag",
        "platform": "linux",
        "environ": {},
        "browsers": browser_names("chrome"),
    }
    install_native_host(
        **kwargs,
        extension_ids=[],
        python_executable="/usr/bin/python3",
    )
    removed = remove_native_host(**kwargs)
    assert removed
    assert all(not path.exists() for path in removed)
    assert DEV_EXTENSION_ID in load_saved_ids(tmp_path / "swag")
    lines = status_lines(
        os_home=tmp_path / "home",
        swag_dir=tmp_path / "swag",
        platform="linux",
        environ={},
    )
    assert lines[0].startswith("host: not installed")


def test_windows_install_writes_registry(tmp_path: Path) -> None:
    registry = MemoryRegistry()
    python = r"C:\Program Files\Python\python.exe"
    report = install_native_host(
        os_home=tmp_path / "home",
        swag_dir=tmp_path / "swag",
        platform="win32",
        environ={"APPDATA": str(tmp_path / "roaming")},
        extension_ids=[],
        browsers=("edge",),
        python_executable=python,
        registry=registry,
    )
    assert report.launcher.suffix == ".bat"
    launcher_text = report.launcher.read_text(encoding="utf-8")
    assert f'"{python}" -u -m swag_bot.extension.host' in launcher_text
    assert report.manifests[0].is_file()
    key = registry_key("edge")
    assert registry.read_value(key) == str(report.manifests[0])
    remove_native_host(
        os_home=tmp_path / "home",
        swag_dir=tmp_path / "swag",
        platform="win32",
        environ={"APPDATA": str(tmp_path / "roaming")},
        browsers=("edge",),
        registry=registry,
    )
    assert registry.read_value(key) is None


def test_browser_name_rejects_unknown() -> None:
    with pytest.raises(SwagError):
        browser_names("brave")


def test_dev_extension_id_matches_manifest_key() -> None:
    import base64
    import hashlib

    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "extension" / "public" / "manifest.json").read_text())
    der = base64.b64decode(manifest["key"])
    digest = hashlib.sha256(der).hexdigest()[:32]
    derived = "".join(chr(ord("a") + int(char, 16)) for char in digest)
    assert derived == DEV_EXTENSION_ID
