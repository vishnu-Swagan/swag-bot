"""``swag gallery`` commands: search, inspect, and install signed plugins."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from swag_bot.interfaces import ActionRequest
from swag_bot.plugins.bundle import canonical_bundle
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.gallery import (
    TrustReport,
    inspect_plugin,
    install_from_gallery,
    load_gallery_index,
    load_secret,
    search_plugins,
    sha256_file,
    sign_plugin,
)
from swag_bot.plugins.gallery_index import GalleryError, GalleryPluginEntry, LoadedIndex
from swag_bot.plugins.minisign import MinisignError, load_public_key, write_keypair
from swag_bot.plugins.scan import blocking_findings

app = typer.Typer(
    help="Search and install plugins from a signed static gallery index.",
    no_args_is_help=True,
)

IndexOption = Annotated[
    str | None,
    typer.Option(
        "--index",
        "-i",
        envvar="SWAG_GALLERY_INDEX",
        help="Gallery index JSON file or http(s) URL. Defaults to SWAG_GALLERY_INDEX.",
    ),
]


def _print_permissions(action: ActionRequest) -> None:
    typer.echo(action.summary)
    permissions = action.arguments.get("permissions") or []
    if permissions:
        typer.echo("Requested permissions:")
        for name in permissions:
            typer.echo(f"  - {name}")
    else:
        typer.echo("Requested permissions: (none)")


class _Prompter:
    def prompt(self, action: ActionRequest) -> bool:
        _print_permissions(action)
        return typer.confirm("Allow this plugin install?", default=False)


@app.command("search")
def search(
    query: Annotated[
        str,
        typer.Argument(help="Substring matched against name, description, and keywords."),
    ] = "",
    index: IndexOption = None,
) -> None:
    """List gallery plugins. An empty query lists the whole index."""
    loaded = _index(index)
    matches = search_plugins(loaded, query)
    if not matches:
        typer.echo("no plugins matched")
        return
    console = Console(no_color=True, soft_wrap=True, width=120)
    table = Table(title=loaded.index.name or "gallery", show_header=True, header_style="bold")
    for column in ("name", "version", "signed", "description"):
        table.add_column(column)
    for plugin in matches:
        table.add_row(
            plugin.name,
            plugin.version or "",
            "yes" if plugin.signature is not None else "no",
            plugin.description or "",
        )
    console.print(table)


@app.command("info")
def info(
    name: Annotated[str, typer.Argument(help="Plugin name in the gallery index.")],
    index: IndexOption = None,
) -> None:
    """Fetch a plugin, verify its signature, and print the scan. Does not install."""
    loaded = _index(index)
    try:
        report = inspect_plugin(loaded, name)
    except PluginError as exc:
        _fail(exc)
    _print_entry(_find(loaded, name))
    _print_trust(report, include_info=True)
    if report.signature != "valid" or blocking_findings(report.findings):
        raise typer.Exit(code=1)


@app.command("install")
def install(
    name: Annotated[str, typer.Argument(help="Plugin name in the gallery index.")],
    index: IndexOption = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Show permissions and install without a prompt."),
    ] = False,
    allow_unsigned: Annotated[
        bool,
        typer.Option("--allow-unsigned", help="Install a plugin that has no signature. Logged."),
    ] = False,
    allow_tampered: Annotated[
        bool,
        typer.Option(
            "--allow-tampered",
            help="Install even when the signature or digest does not verify. Logged.",
        ),
    ] = False,
    allow_scan: Annotated[
        bool,
        typer.Option("--allow-scan", help="Install even when the scanner reports a block. Logged."),
    ] = False,
    trust_new_key: Annotated[
        bool,
        typer.Option(
            "--trust-new-key",
            help="Replace the publisher key pinned for this plugin name. Logged.",
        ),
    ] = False,
) -> None:
    """Verify the signature and scan, then ask before granting permissions."""
    try:
        result = install_from_gallery(
            name,
            index=_require_index(index),
            prompter=_Prompter(),
            assume_yes=yes,
            allow_unsigned=allow_unsigned,
            allow_tampered=allow_tampered,
            allow_scan=allow_scan,
            trust_new_key=trust_new_key,
            announce=_print_permissions if yes else None,
            on_trust=_print_trust,
        )
    except PluginError as exc:
        _fail(exc)
    if result.overrides:
        typer.echo(
            f"override logged ({', '.join(result.overrides)}): {result.audit_path}",
            err=True,
        )
    record = result.record
    state = "yes" if record.enabled else "no"
    typer.echo(f"installed {record.name} {record.version or 'unversioned'} (enabled: {state})")
    typer.echo(f"source: {record.source}")


@app.command("keygen")
def keygen(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Directory for minisign.pub and minisign.key."),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing key pair in the output directory."),
    ] = False,
) -> None:
    """Write an unencrypted minisign key pair. Keep the secret key private."""
    try:
        secret_path, public_path = write_keypair(output, force=force)
        public = load_public_key(public_path.read_text(encoding="utf-8"))
    except (MinisignError, OSError) as exc:
        _fail(GalleryError(str(exc)))
    typer.echo(f"secret key: {secret_path.resolve()}")
    typer.echo(f"public key: {public_path.resolve()}")
    typer.echo("Keep the secret key private. Publish only the public key.")
    typer.echo(f"minisign -Vm <file> -P {public.b64_line()}")


@app.command("sign")
def sign(
    plugin: Annotated[
        Path,
        typer.Argument(help="Plugin root (the directory with .claude-plugin/)."),
    ],
    secret_key: Annotated[
        Path,
        typer.Option("--secret-key", "-s", help="Unencrypted minisign secret key."),
    ],
    trusted_comment: Annotated[
        str | None,
        typer.Option("--trusted-comment", "-t", help="Single-line trusted comment."),
    ] = None,
) -> None:
    """Sign a plugin directory and print the gallery index entry."""
    try:
        secret = load_secret(secret_key)
        source: dict[str, object] = {"type": "path", "path": str(plugin)}
        signed = sign_plugin(plugin, secret, trusted_comment=trusted_comment, source=source)
    except PluginError as exc:
        _fail(exc)
    typer.echo(f"signed {signed.entry.get('name', '')}")
    typer.echo(f"key id: {signed.key_id}")
    typer.echo(f"digest: sha256:{signed.digest}")
    typer.echo(f"signature: {signed.signature_path}")
    typer.echo(json.dumps(signed.entry, indent=2))


@app.command("bundle")
def bundle(
    plugin: Annotated[Path, typer.Argument(help="Plugin root to hash.")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Where to write the canonical bundle bytes."),
    ],
) -> None:
    """Write the canonical bundle a publisher can sign with the minisign CLI."""
    try:
        payload = canonical_bundle(plugin)
    except PluginError as exc:
        _fail(exc)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    typer.echo(f"wrote {output}")
    typer.echo(f"digest: sha256:{sha256_file(output)}")


def _index(source: str | None) -> LoadedIndex:
    try:
        return load_gallery_index(_require_index(source))
    except PluginError as exc:
        _fail(exc)


def _require_index(source: str | None) -> str:
    if source is None or not source.strip():
        _fail(GalleryError("pass --index or set SWAG_GALLERY_INDEX"))
    return source


def _find(loaded: LoadedIndex, name: str) -> GalleryPluginEntry:
    try:
        return loaded.find(name)
    except PluginError as exc:
        _fail(exc)


def _print_entry(entry: GalleryPluginEntry) -> None:
    typer.echo(f"name: {entry.name}")
    typer.echo(f"version: {entry.version or '(none)'}")
    typer.echo(f"description: {entry.description or '(none)'}")
    if entry.author:
        typer.echo(f"author: {entry.author}")
    if entry.license:
        typer.echo(f"license: {entry.license}")
    typer.echo(f"source: {entry.source.type}")


def _print_trust(report: TrustReport, include_info: bool = False) -> None:
    typer.echo(f"signature: {report.signature}")
    if report.key_id:
        typer.echo(f"key id: {report.key_id}")
    typer.echo(f"detail: {report.detail}")
    typer.echo(f"digest: sha256:{report.digest}")
    if report.permissions:
        typer.echo("permissions: " + ", ".join(report.permissions))
    else:
        typer.echo("permissions: (none)")
    blocked = [item for item in report.findings if item.severity == "block"]
    warnings = [item for item in report.findings if item.severity == "warn"]
    typer.echo(f"scan: {len(blocked)} blocking, {len(warnings)} warnings")
    for finding in report.findings:
        if finding.severity == "info" and not include_info:
            continue
        location = finding.path if finding.line is None else f"{finding.path}:{finding.line}"
        typer.echo(f"  {finding.severity} {location} {finding.rule}: {finding.message}")


def _fail(exc: PluginError) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc
