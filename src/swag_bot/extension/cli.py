"""``swag extension`` commands.

``install`` writes the native host manifest. Chrome starts the host itself.
There is no server to leave running.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from swag_bot.config import swag_home
from swag_bot.errors import SwagError
from swag_bot.extension.install import (
    browser_names,
    current_environ,
    current_platform,
    install_native_host,
    remove_native_host,
    status_lines,
)

app = typer.Typer(
    help="Connect the Chrome extension to Swag Bot on this computer.",
    no_args_is_help=True,
)


def os_home() -> Path:
    """Home directory used for browser config. Tests patch this."""
    return Path.home()


@app.command("install")
def install(
    extension_id: Annotated[
        list[str] | None,
        typer.Option(
            "--extension-id",
            help="Chrome extension id to allow. Repeat for more than one. "
            "The unpacked id is always included.",
        ),
    ] = None,
    browser: Annotated[
        str,
        typer.Option(help="chrome, chromium, edge, or all."),
    ] = "all",
) -> None:
    """Register the native messaging host for Chrome, Chromium, and Edge."""
    try:
        browsers = browser_names(browser)
        report = install_native_host(
            os_home=os_home(),
            swag_dir=swag_home(),
            platform=current_platform(),
            environ=current_environ(),
            extension_ids=extension_id or [],
            browsers=browsers,
            python_executable=sys_executable(),
        )
    except SwagError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Registered the Swag Bot native messaging host.")
    typer.echo(f"Host: {report.launcher}")
    typer.echo("Browsers: " + ", ".join(report.browsers))
    typer.echo("Extension ids: " + ", ".join(report.extension_ids))
    for path in report.manifests:
        typer.echo(f"Manifest: {path}")
    for key in report.registry_keys:
        typer.echo(f"Registry: HKCU\\{key}")
    typer.echo("")
    typer.echo("Quit Chrome completely and open it again so it loads the host.")
    typer.echo("Then click the Swag Bot icon to open the side panel.")


@app.command("remove")
def remove(
    browser: Annotated[
        str,
        typer.Option(help="chrome, chromium, edge, or all."),
    ] = "all",
) -> None:
    """Remove the native messaging host manifests. Saved extension ids stay."""
    try:
        browsers = browser_names(browser)
        removed = remove_native_host(
            os_home=os_home(),
            swag_dir=swag_home(),
            platform=current_platform(),
            environ=current_environ(),
            browsers=browsers,
        )
    except SwagError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if not removed:
        typer.echo("No native messaging host was installed.")
        return
    typer.echo("Removed the Swag Bot native messaging host.")
    for path in removed:
        typer.echo(str(path))


@app.command("status")
def status() -> None:
    """Show whether the native messaging host is registered."""
    try:
        lines = status_lines(
            os_home=os_home(),
            swag_dir=swag_home(),
            platform=current_platform(),
            environ=current_environ(),
        )
    except SwagError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    for line in lines:
        typer.echo(line)
    if lines and lines[0].startswith("host: not installed"):
        typer.echo("Run `swag extension install` to register the host.")


@app.command("host")
def host() -> None:
    """Speak the native messaging protocol on stdin. Chrome launches this."""
    from swag_bot.extension.host import main

    main()


def sys_executable() -> str:
    """Python used for the host launcher. Tests patch this."""
    import sys

    return sys.executable
