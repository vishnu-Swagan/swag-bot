"""Install the native messaging host for Chrome, Chromium, and Edge.

The host manifest names this extension and nothing else. Chrome refuses to
deliver messages from a web page or from a different extension. There is no
listening port.

Linux and macOS write a manifest into each browser's user-level
``NativeMessagingHosts`` directory. Windows writes one manifest under
``SWAG_HOME`` and points ``HKCU`` registry keys at it. User-level paths do
not need an administrator.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from swag_bot.errors import SwagError
from swag_bot.extension.ids import DEV_EXTENSION_ID, HOST_NAME

_BROWSERS = ("chrome", "chromium", "edge")

_LINUX_DIRS = {
    "chrome": "google-chrome",
    "chromium": "chromium",
    "edge": "microsoft-edge",
}

_MAC_DIRS = {
    "chrome": "Google/Chrome",
    "chromium": "Chromium",
    "edge": "Microsoft Edge",
}

_WINDOWS_KEYS = {
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "chromium": r"Software\Chromium\NativeMessagingHosts",
    "edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
}


class RegistryWriter(Protocol):
    """The three registry operations the Windows install needs."""

    def set_value(self, key_path: str, value: str) -> None:
        """Set the default value of ``key_path``."""
        ...

    def delete_key(self, key_path: str) -> None:
        """Remove ``key_path``. A missing key is not an error."""
        ...

    def read_value(self, key_path: str) -> str | None:
        """Return the default value, or None when the key is absent."""
        ...


@dataclass(frozen=True)
class InstallReport:
    """What ``install_native_host`` wrote."""

    launcher: Path
    manifests: tuple[Path, ...]
    extension_ids: tuple[str, ...]
    browsers: tuple[str, ...]
    registry_keys: tuple[str, ...]


def extension_origin(extension_id: str) -> str:
    """The ``allowed_origins`` entry for one extension id."""
    return f"chrome-extension://{normalize_extension_id(extension_id)}/"


def normalize_extension_id(extension_id: str) -> str:
    """Return a Chrome extension id, or raise ``SwagError``."""
    cleaned = extension_id.strip().lower()
    if len(cleaned) != 32 or any(char not in "abcdefghijklmnop" for char in cleaned):
        raise SwagError(
            "extension id must be 32 characters from a to p (the id shown on chrome://extensions)"
        )
    return cleaned


def merge_extension_ids(extra: Sequence[str], saved: Sequence[str] = ()) -> tuple[str, ...]:
    """Dev id first, then saved ids, then ``extra``. Duplicates collapse."""
    ordered: list[str] = []
    for raw in (DEV_EXTENSION_ID, *saved, *extra):
        cleaned = normalize_extension_id(raw)
        if cleaned not in ordered:
            ordered.append(cleaned)
    return tuple(ordered)


def host_manifest(launcher: Path, extension_ids: Sequence[str]) -> dict[str, object]:
    """Native host manifest. ``allowed_origins`` is only these extension ids."""
    return {
        "name": HOST_NAME,
        "description": "Swag Bot native messaging host",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [extension_origin(item) for item in extension_ids],
    }


def browser_names(selection: str) -> tuple[str, ...]:
    """``all`` or one of chrome, chromium, edge."""
    cleaned = selection.strip().lower()
    if cleaned == "all":
        return _BROWSERS
    if cleaned in _BROWSERS:
        return (cleaned,)
    raise SwagError("browser must be chrome, chromium, edge, or all")


def config_home(os_home: Path, platform: str, environ: Mapping[str, str]) -> Path:
    """Directory that holds browser user-data dirs on this platform."""
    if platform == "linux":
        xdg = environ.get("XDG_CONFIG_HOME", "").strip()
        if xdg:
            return Path(xdg)
        return os_home / ".config"
    if platform == "darwin":
        return os_home / "Library" / "Application Support"
    if platform == "win32":
        appdata = environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata)
        return os_home / "AppData" / "Roaming"
    raise SwagError(f"unsupported platform for the native host: {platform}")


def manifest_path(
    *,
    os_home: Path,
    swag_dir: Path,
    platform: str,
    environ: Mapping[str, str],
    browser: str,
) -> Path:
    """Where that browser reads the host manifest."""
    name = f"{HOST_NAME}.json"
    if platform == "win32":
        return swag_dir / "native-messaging" / name
    root = config_home(os_home, platform, environ)
    if platform == "linux":
        directory = _LINUX_DIRS[browser]
        return root / directory / "NativeMessagingHosts" / name
    if platform == "darwin":
        directory = _MAC_DIRS[browser]
        return root / directory / "NativeMessagingHosts" / name
    raise SwagError(f"unsupported platform for the native host: {platform}")


def registry_key(browser: str) -> str:
    """HKCU path whose default value is the manifest file."""
    return _WINDOWS_KEYS[browser] + "\\" + HOST_NAME


def install_native_host(
    *,
    os_home: Path,
    swag_dir: Path,
    platform: str,
    environ: Mapping[str, str],
    extension_ids: Sequence[str],
    browsers: Sequence[str],
    python_executable: str,
    registry: RegistryWriter | None = None,
) -> InstallReport:
    """Write the launcher and the host manifests. Return what was written."""
    ids = merge_extension_ids(extension_ids, saved=load_saved_ids(swag_dir))
    chosen = tuple(browsers)
    for browser in chosen:
        if browser not in _BROWSERS:
            raise SwagError("browser must be chrome, chromium, edge, or all")
    launcher = _write_launcher(swag_dir, platform, python_executable)
    payload = host_manifest(launcher, ids)
    written: list[Path] = []
    keys: list[str] = []
    if platform == "win32":
        path = manifest_path(
            os_home=os_home,
            swag_dir=swag_dir,
            platform=platform,
            environ=environ,
            browser=chosen[0],
        )
        _write_json(path, payload)
        written.append(path)
        writer = registry if registry is not None else WindowsRegistry()
        for browser in chosen:
            key = registry_key(browser)
            writer.set_value(key, str(path))
            keys.append(key)
    else:
        for browser in chosen:
            path = manifest_path(
                os_home=os_home,
                swag_dir=swag_dir,
                platform=platform,
                environ=environ,
                browser=browser,
            )
            _write_json(path, payload)
            written.append(path)
    save_ids(swag_dir, ids)
    return InstallReport(
        launcher=launcher,
        manifests=tuple(written),
        extension_ids=ids,
        browsers=chosen,
        registry_keys=tuple(keys),
    )


def remove_native_host(
    *,
    os_home: Path,
    swag_dir: Path,
    platform: str,
    environ: Mapping[str, str],
    browsers: Sequence[str],
    registry: RegistryWriter | None = None,
) -> tuple[Path, ...]:
    """Delete host manifests and the launcher. Saved extension ids stay."""
    removed: list[Path] = []
    launcher = _launcher_path(swag_dir, platform)
    if launcher.is_file():
        launcher.unlink()
        removed.append(launcher)
    if platform == "win32":
        path = manifest_path(
            os_home=os_home,
            swag_dir=swag_dir,
            platform=platform,
            environ=environ,
            browser=browsers[0],
        )
        if path.is_file():
            path.unlink()
            removed.append(path)
        writer = registry if registry is not None else WindowsRegistry()
        for browser in browsers:
            writer.delete_key(registry_key(browser))
    else:
        for browser in browsers:
            path = manifest_path(
                os_home=os_home,
                swag_dir=swag_dir,
                platform=platform,
                environ=environ,
                browser=browser,
            )
            if path.is_file() or path.is_symlink():
                path.unlink()
                removed.append(path)
    return tuple(removed)


def status_lines(
    *,
    os_home: Path,
    swag_dir: Path,
    platform: str,
    environ: Mapping[str, str],
    registry: RegistryWriter | None = None,
) -> list[str]:
    """Plain lines for ``swag extension status``. No secrets are included."""
    launcher = _launcher_path(swag_dir, platform)
    lines = [f"host: {'installed' if launcher.is_file() else 'not installed'} ({launcher})"]
    ids = load_saved_ids(swag_dir)
    lines.append("extension ids: " + (", ".join(ids) if ids else "(none saved)"))
    if platform == "win32":
        path = manifest_path(
            os_home=os_home,
            swag_dir=swag_dir,
            platform=platform,
            environ=environ,
            browser="chrome",
        )
        lines.append(f"manifest: {'present' if path.is_file() else 'absent'} ({path})")
        writer = registry if registry is not None else WindowsRegistry()
        for browser in _BROWSERS:
            current = writer.read_value(registry_key(browser))
            lines.append(f"{browser}: {current or 'not registered'}")
        return lines
    for browser in _BROWSERS:
        path = manifest_path(
            os_home=os_home,
            swag_dir=swag_dir,
            platform=platform,
            environ=environ,
            browser=browser,
        )
        state = "present" if path.is_file() else "absent"
        lines.append(f"{browser}: {state} ({path})")
    return lines


def ids_path(swag_dir: Path) -> Path:
    """Where extra extension ids are remembered."""
    return swag_dir / "extension.json"


def load_saved_ids(swag_dir: Path) -> tuple[str, ...]:
    """Ids from ``extension.json``. A missing or broken file is empty."""
    path = ids_path(swag_dir)
    if not path.is_file():
        return ()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ()
    if not isinstance(loaded, dict):
        return ()
    raw = loaded.get("extension_ids", [])
    if not isinstance(raw, list):
        return ()
    found: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        try:
            cleaned = normalize_extension_id(item)
        except SwagError:
            continue
        if cleaned not in found:
            found.append(cleaned)
    return tuple(found)


def save_ids(swag_dir: Path, extension_ids: Sequence[str]) -> None:
    """Remember extension ids so the next install keeps them."""
    path = ids_path(swag_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"extension_ids": list(extension_ids)}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class WindowsRegistry:
    """HKCU native-messaging keys. Imported only on Windows."""

    def set_value(self, key_path: str, value: str) -> None:
        winreg = _winreg()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)

    def delete_key(self, key_path: str) -> None:
        winreg = _winreg()
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            return

    def read_value(self, key_path: str) -> str | None:
        winreg = _winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                data, _typ = winreg.QueryValueEx(key, "")
        except OSError:
            return None
        if isinstance(data, str):
            return data
        return None


def _winreg() -> Any:
    import winreg

    return winreg


def _launcher_path(swag_dir: Path, platform: str) -> Path:
    directory = swag_dir / "native-messaging"
    if platform == "win32":
        return directory / "swag-bot-host.bat"
    return directory / "swag-bot-host"


def _write_launcher(swag_dir: Path, platform: str, python_executable: str) -> Path:
    if not python_executable:
        raise SwagError("python executable path is empty")
    path = _launcher_path(swag_dir, platform)
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform == "win32":
        quoted = _quote_windows(python_executable)
        path.write_text(
            f"@echo off\r\n{quoted} -u -m swag_bot.extension.host\r\n",
            encoding="utf-8",
        )
        return path
    quoted = _quote_sh(python_executable)
    path.write_text(f"#!/bin/sh\nexec {quoted} -u -m swag_bot.extension.host\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _quote_sh(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _quote_windows(value: str) -> str:
    return '"' + value.replace('"', "") + '"'


def current_platform() -> str:
    """``sys.platform`` for the CLI. Tests patch this."""
    return sys.platform


def current_environ() -> Mapping[str, str]:
    """Process environment. Tests patch this."""
    return os.environ
