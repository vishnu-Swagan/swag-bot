"""Search, verify, scan, and install plugins from a static gallery index.

Signature and scan checks run before ``install_plugin``. That function still
shows the permission grant and writes ``grants.json``. Unsigned or tampered
plugins are refused unless the caller passes an override, which is appended
to ``$SWAG_HOME/gallery/audit.jsonl``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from swag_bot.config import swag_home
from swag_bot.interfaces import ApprovalPrompter, GrantStore
from swag_bot.plugins.bundle import (
    GALLERY_META_DIR,
    bundle_digest,
    canonical_bundle,
)
from swag_bot.plugins.errors import PluginError
from swag_bot.plugins.gallery_index import (
    GalleryError,
    GalleryPluginEntry,
    LoadedIndex,
    index_base_dir,
    parse_index,
)
from swag_bot.plugins.installer import (
    Announce,
    InstallRecord,
    default_clone,
    install_plugin,
)
from swag_bot.plugins.loader import load_plugin
from swag_bot.plugins.marketplace import CloneFn
from swag_bot.plugins.minisign import (
    MinisignError,
    SecretKey,
    load_public_key,
    load_secret_key,
    load_signature,
    sign_message,
    verify_message,
)
from swag_bot.plugins.scan import ScanFinding, blocking_findings, scan_plugin

FetchFn = Callable[[str], bytes]

_INDEX_LIMIT = 2 * 1024 * 1024
_ARCHIVE_LIMIT = 20 * 1024 * 1024
_USER_AGENT = "swag-bot-gallery/0.1"
_AUDIT_NAME = "audit.jsonl"
_PIN_NAME = "trusted-keys.json"


@dataclass(frozen=True)
class TrustReport:
    """Signature, digest, and scan result for one gallery plugin."""

    name: str
    version: str | None
    signature: str
    detail: str
    key_id: str | None
    public_key: str | None
    digest: str
    permissions: list[str]
    findings: list[ScanFinding]
    pin_mismatch: bool


@dataclass(frozen=True)
class GalleryInstall:
    """A completed gallery install, including which overrides were required."""

    record: InstallRecord
    report: TrustReport
    overrides: list[str]
    audit_path: Path


@dataclass(frozen=True)
class SignedPlugin:
    """Result of ``sign_plugin``. Paths are under ``.swag-gallery/``."""

    digest: str
    key_id: str
    public_key: str
    signature_text: str
    signature_path: Path
    entry: dict[str, object]


def search_plugins(loaded: LoadedIndex, query: str) -> list[GalleryPluginEntry]:
    """Case-insensitive substring match on name, description, and keywords."""
    needle = query.strip().casefold()
    if not needle:
        return list(loaded.index.plugins)
    matches: list[GalleryPluginEntry] = []
    for plugin in loaded.index.plugins:
        haystack = " ".join(
            (
                plugin.name,
                plugin.description or "",
                plugin.author or "",
                " ".join(plugin.keywords),
            )
        ).casefold()
        if needle in haystack:
            matches.append(plugin)
    return matches


def load_gallery_index(source: str, *, fetch: FetchFn | None = None) -> LoadedIndex:
    """Read a gallery index from a local path or an ``http(s)`` URL."""
    text = source.strip()
    if not text:
        raise GalleryError("gallery index is empty; pass --index or set SWAG_GALLERY_INDEX")
    base = index_base_dir(text)
    data = _read_bytes(text, limit=_INDEX_LIMIT, fetch=fetch, label="gallery index")
    return parse_index(data, source=text, base_dir=base)


def inspect_plugin(
    loaded: LoadedIndex,
    name: str,
    *,
    home: Path | None = None,
    clone: CloneFn | None = None,
    fetch: FetchFn | None = None,
) -> TrustReport:
    """Fetch ``name``, verify its signature, and scan it. Does not install."""
    entry = loaded.find(name)
    with tempfile.TemporaryDirectory(prefix="swag-gallery-") as tmp:
        root = _materialize(entry, loaded, Path(tmp), clone=clone, fetch=fetch)
        return _assess(root, entry, home=_home(home))


def install_from_gallery(
    name: str,
    *,
    index: str,
    prompter: ApprovalPrompter | None = None,
    assume_yes: bool = False,
    allow_unsigned: bool = False,
    allow_tampered: bool = False,
    allow_scan: bool = False,
    trust_new_key: bool = False,
    home: Path | None = None,
    clone: CloneFn | None = None,
    announce: Announce | None = None,
    grant_store: GrantStore | None = None,
    fetch: FetchFn | None = None,
    on_trust: Callable[[TrustReport], None] | None = None,
) -> GalleryInstall:
    """Verify, scan, then run the existing install-time permission grant.

    Overrides are refused by default. Each override that was required to
    proceed is appended to the gallery audit log before the plugin is copied.
    """
    loaded = load_gallery_index(index, fetch=fetch)
    entry = loaded.find(name)
    home_dir = _home(home)
    with tempfile.TemporaryDirectory(prefix="swag-gallery-") as tmp:
        root = _materialize(entry, loaded, Path(tmp), clone=clone, fetch=fetch)
        report = _assess(root, entry, home=home_dir)
        if on_trust is not None:
            on_trust(report)
        overrides = _required_overrides(
            report,
            allow_unsigned=allow_unsigned,
            allow_tampered=allow_tampered,
            allow_scan=allow_scan,
            trust_new_key=trust_new_key,
        )
        audit_path = _audit_path(home_dir)
        if overrides is None:
            _audit(home_dir, report, loaded.source, overrides=[], outcome="refused")
            raise GalleryError(_refusal_message(report, audit_path))
        label = f"gallery:{loaded.source}#{entry.name}@{entry.version or report.version or ''}"
        try:
            record = install_plugin(
                str(root),
                prompter=prompter,
                assume_yes=assume_yes,
                plugin_name=entry.name,
                home=home,
                clone=clone,
                announce=announce,
                grant_store=grant_store,
                source_label=label,
            )
        except PluginError:
            _audit(home_dir, report, loaded.source, overrides=overrides, outcome="denied")
            raise
        if report.signature == "valid" and report.public_key:
            _pin(home_dir, report.name, report.public_key, report.key_id or "")
        _audit(home_dir, report, loaded.source, overrides=overrides, outcome="installed")
        return GalleryInstall(record, report, overrides, audit_path)


def sign_plugin(
    root: Path,
    secret: SecretKey,
    *,
    trusted_comment: str | None = None,
    source: dict[str, object] | None = None,
) -> SignedPlugin:
    """Sign ``root`` and write ``.swag-gallery/`` next to the plugin files."""
    plugin = load_plugin(root)
    bundle = canonical_bundle(root)
    digest = bundle_digest(bundle)
    signature = sign_message(
        bundle,
        secret,
        trusted_comment=trusted_comment,
        filename=f"{plugin.manifest.name}.bundle",
    )
    public = secret.public_key()
    meta = root / GALLERY_META_DIR
    meta.mkdir(parents=True, exist_ok=True)
    signature_path = meta / "signature.minisig"
    signature_path.write_text(signature.file_text(), encoding="utf-8")
    (meta / "public.key").write_text(public.file_text(), encoding="utf-8")
    (meta / "digest.sha256").write_text(digest + "\n", encoding="utf-8")
    entry = index_entry(
        root,
        source=source
        if source is not None
        else {"type": "path", "path": str(root.expanduser().resolve())},
    )
    return SignedPlugin(
        digest=digest,
        key_id=public.key_id_hex,
        public_key=public.b64_line(),
        signature_text=signature.file_text(),
        signature_path=signature_path,
        entry=entry,
    )


def index_entry(root: Path, *, source: dict[str, object]) -> dict[str, object]:
    """JSON object for one signed plugin. The publisher pastes it into the index."""
    plugin = load_plugin(root)
    manifest = plugin.manifest
    bundle = canonical_bundle(root)
    meta = root / GALLERY_META_DIR
    signature_path = meta / "signature.minisig"
    public_path = meta / "public.key"
    if not signature_path.is_file() or not public_path.is_file():
        raise GalleryError(f"{root} has no {GALLERY_META_DIR} signature; run swag gallery sign")
    public = load_public_key(public_path.read_text(encoding="utf-8"))
    payload: dict[str, object] = {
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "license": manifest.license,
        "keywords": list(manifest.keywords),
        "permissions": list(manifest.permissions),
        "source": source,
        "digest": {"algorithm": "sha256", "value": bundle_digest(bundle)},
        "signature": {
            "scheme": "minisign",
            "public_key": public.b64_line(),
            "file": signature_path.read_text(encoding="utf-8"),
        },
    }
    if manifest.author is not None:
        payload["author"] = manifest.author.name
    return {key: value for key, value in payload.items() if value is not None}


def _assess(root: Path, entry: GalleryPluginEntry, *, home: Path) -> TrustReport:
    plugin = load_plugin(root)
    if plugin.manifest.name != entry.name:
        raise GalleryError(
            f"plugin.json name is {plugin.manifest.name!r}, not gallery name {entry.name!r}"
        )
    bundle = canonical_bundle(root)
    digest = bundle_digest(bundle)
    reasons: list[str] = []
    if entry.version is not None and plugin.manifest.version != entry.version:
        reasons.append(
            f"index version {entry.version!r} does not match "
            f"plugin.json {plugin.manifest.version!r}"
        )
    if entry.permissions is not None and set(entry.permissions) != set(plugin.manifest.permissions):
        reasons.append("index permissions do not match plugin.json")
    if entry.digest is not None and entry.digest.value != digest:
        reasons.append("index digest does not match the plugin bundle")
    signature_text, public_text, conflict = _signature_material(root, entry)
    if conflict:
        reasons.append(conflict)
    key_id: str | None = None
    public_line: str | None = None
    if signature_text is None:
        state = "tampered" if reasons else "unsigned"
        detail = "plugin is not signed" if not reasons else "; ".join(reasons)
    else:
        state, detail, key_id, public_line = _verify_signature(
            bundle, signature_text, public_text, reasons
        )
    findings = scan_plugin(root, list(plugin.manifest.permissions))
    pinned = _pinned_key(home, plugin.manifest.name)
    mismatch = bool(public_line and pinned and pinned != public_line and state == "valid")
    if mismatch:
        detail = f"{detail}; publisher key does not match the key pinned for this plugin"
    return TrustReport(
        name=plugin.manifest.name,
        version=plugin.manifest.version,
        signature=state,
        detail=detail,
        key_id=key_id,
        public_key=public_line,
        digest=digest,
        permissions=list(plugin.manifest.permissions),
        findings=findings,
        pin_mismatch=mismatch,
    )


def _verify_signature(
    bundle: bytes,
    signature_text: str,
    public_text: str | None,
    reasons: list[str],
) -> tuple[str, str, str | None, str | None]:
    try:
        signature = load_signature(signature_text)
        public = load_public_key(public_text) if public_text else None
    except MinisignError as exc:
        extra = f"; {'; '.join(reasons)}" if reasons else ""
        return "tampered", f"{exc}{extra}", None, None
    if public is None:
        extra = f"; {'; '.join(reasons)}" if reasons else ""
        return "tampered", f"signature has no public key{extra}", None, None
    result = verify_message(bundle, signature, public)
    line = public.b64_line()
    if result.ok and not reasons:
        return "valid", "minisign signature verified", result.key_id, line
    if result.ok:
        return "tampered", "; ".join(reasons), result.key_id, line
    extra = f"; {'; '.join(reasons)}" if reasons else ""
    return "tampered", f"{result.reason}{extra}", result.key_id, line


def _required_overrides(
    report: TrustReport,
    *,
    allow_unsigned: bool,
    allow_tampered: bool,
    allow_scan: bool,
    trust_new_key: bool,
) -> list[str] | None:
    """Overrides that apply. ``None`` means the install must be refused."""
    needed: list[tuple[str, bool]] = []
    if report.signature == "unsigned":
        needed.append(("allow-unsigned", allow_unsigned))
    if report.signature == "tampered":
        needed.append(("allow-tampered", allow_tampered))
    if blocking_findings(report.findings):
        needed.append(("allow-scan", allow_scan))
    if report.pin_mismatch:
        needed.append(("trust-new-key", trust_new_key))
    if any(not granted for _name, granted in needed):
        return None
    return [name for name, granted in needed if granted]


def _refusal_message(report: TrustReport, audit_path: Path) -> str:
    parts: list[str] = []
    if report.signature == "unsigned":
        parts.append("plugin is not signed (pass --allow-unsigned to override)")
    elif report.signature == "tampered":
        parts.append(
            f"plugin signature check failed: {report.detail} "
            "(pass --allow-tampered to override)"
        )
    blocked = blocking_findings(report.findings)
    if blocked:
        shown = "; ".join(f"{item.rule} at {item.path}" for item in blocked[:5])
        parts.append(
            f"scan found {len(blocked)} blocking finding(s): {shown} "
            "(pass --allow-scan to override)"
        )
    if report.pin_mismatch:
        parts.append(
            "publisher key changed since the last signed install "
            "(pass --trust-new-key to override)"
        )
    if not parts:
        parts.append(report.detail)
    joined = " ".join(parts)
    return (
        f"refusing gallery install of {report.name!r}: {joined}. "
        f"Decision logged at {audit_path}."
    )


def _signature_material(
    root: Path,
    entry: GalleryPluginEntry,
) -> tuple[str | None, str | None, str | None]:
    meta = root / GALLERY_META_DIR
    file_sig = _read_text(meta / "signature.minisig")
    file_key = _read_text(meta / "public.key")
    index_sig = entry.signature.file if entry.signature is not None else None
    index_key = entry.signature.public_key if entry.signature is not None else None
    conflict: str | None = None
    if file_sig and index_sig and _signature_core(file_sig) != _signature_core(index_sig):
        conflict = "index signature does not match .swag-gallery/signature.minisig"
    if file_key and index_key and _public_core(file_key) != _public_core(index_key):
        conflict = "index public key does not match .swag-gallery/public.key"
    return index_sig or file_sig, index_key or file_key, conflict


def _signature_core(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[1] if len(lines) > 1 else text.strip()


def _public_core(text: str) -> str:
    try:
        return load_public_key(text).b64_line()
    except MinisignError:
        return " ".join(text.split())


def _materialize(
    entry: GalleryPluginEntry,
    loaded: LoadedIndex,
    workdir: Path,
    *,
    clone: CloneFn | None,
    fetch: FetchFn | None,
) -> Path:
    source = entry.source
    if source.type == "path":
        if source.path is None:
            raise GalleryError(f"plugin {entry.name!r} path source is missing path")
        raw = Path(source.path).expanduser()
        if not raw.is_absolute():
            if loaded.base_dir is None:
                raise GalleryError(
                    f"plugin {entry.name!r} uses a relative path; the index must be a local file"
                )
            raw = loaded.base_dir / raw
        if not raw.is_dir():
            raise GalleryError(f"plugin source does not exist: {raw}")
        return raw.resolve()
    cloner = clone if clone is not None else default_clone
    if source.type == "github":
        repo = source.repo or ""
        if repo.count("/") != 1:
            raise GalleryError(f"plugin {entry.name!r} github source needs owner/repo")
        dest = workdir / "repo"
        cloner(f"https://github.com/{repo}.git", dest, source.ref)
        return dest
    if source.type == "git":
        if not source.url:
            raise GalleryError(f"plugin {entry.name!r} git source needs a url")
        dest = workdir / "repo"
        cloner(source.url, dest, source.ref)
        return dest
    if not source.url:
        raise GalleryError(f"plugin {entry.name!r} archive source needs a url")
    payload = _read_bytes(source.url, limit=_ARCHIVE_LIMIT, fetch=fetch, label="plugin archive")
    dest = workdir / "archive"
    dest.mkdir()
    _extract_archive(payload, dest, label=source.url)
    return _plugin_root(dest)


def _extract_archive(payload: bytes, dest: Path, *, label: str) -> None:
    if payload[:2] == b"PK":
        _extract_zip(payload, dest, label=label)
        return
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            _extract_tar(archive, dest)
    except tarfile.TarError as exc:
        raise GalleryError(f"{label}: not a tar or zip archive ({exc})") from exc


def _extract_tar(archive: tarfile.TarFile, dest: Path) -> None:
    for member in archive.getmembers():
        _reject_archive_name(member.name)
        if member.issym() or member.islnk():
            raise GalleryError(f"archive member is a link: {member.name}")
        if member.isdir():
            (dest / member.name).mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            continue
        extracted = archive.extractfile(member)
        if extracted is None:
            continue
        target = dest / member.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(extracted.read())


def _extract_zip(payload: bytes, dest: Path, *, label: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for info in archive.infolist():
                _reject_archive_name(info.filename)
                target = dest / info.filename
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
    except zipfile.BadZipFile as exc:
        raise GalleryError(f"{label}: invalid zip archive ({exc})") from exc


def _reject_archive_name(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise GalleryError(f"archive path escapes the archive: {name}")


def _plugin_root(dest: Path) -> Path:
    if (dest / ".claude-plugin" / "plugin.json").is_file():
        return dest
    children = [path for path in dest.iterdir() if path.name != "__MACOSX"]
    if len(children) == 1 and (children[0] / ".claude-plugin" / "plugin.json").is_file():
        return children[0]
    raise GalleryError(f"archive has no .claude-plugin/plugin.json under {dest}")


def _read_bytes(source: str, *, limit: int, fetch: FetchFn | None, label: str) -> bytes:
    if source.startswith(("http://", "https://")):
        if fetch is not None:
            data = fetch(source)
        else:
            request = urllib.request.Request(source, headers={"User-Agent": _USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read(limit + 1)
            except urllib.error.URLError as exc:
                raise GalleryError(f"could not fetch {label} {source}: {exc}") from exc
        if len(data) > limit:
            raise GalleryError(f"{label} exceeds {limit} bytes: {source}")
        return data
    if source.startswith("file:"):
        from urllib.parse import urlparse

        path = Path(urlparse(source).path)
    else:
        path = Path(source).expanduser()
    if not path.is_file():
        raise GalleryError(f"{label} does not exist: {path}")
    data = path.read_bytes()
    if len(data) > limit:
        raise GalleryError(f"{label} exceeds {limit} bytes: {path}")
    return data


def _read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _home(home: Path | None) -> Path:
    return (home if home is not None else swag_home()).expanduser()


def _gallery_dir(home: Path) -> Path:
    return home / "gallery"


def _audit_path(home: Path) -> Path:
    return _gallery_dir(home) / _AUDIT_NAME


def _pin_path(home: Path) -> Path:
    return _gallery_dir(home) / _PIN_NAME


def _audit(
    home: Path,
    report: TrustReport,
    index: str,
    *,
    overrides: list[str],
    outcome: str,
) -> None:
    path = _audit_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocked = [
        f"{item.rule}:{item.path}:{item.line or 0}" for item in blocking_findings(report.findings)
    ]
    record = {
        "time": datetime.now(UTC).isoformat(),
        "event": "gallery_install",
        "plugin": report.name,
        "version": report.version or "",
        "index": index,
        "signature": report.signature,
        "detail": report.detail,
        "key_id": report.key_id or "",
        "digest": f"sha256:{report.digest}",
        "blocking": blocked,
        "overrides": overrides,
        "outcome": outcome,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _pinned_key(home: Path, name: str) -> str | None:
    path = _pin_path(home)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GalleryError(f"cannot read trusted gallery keys {path}: {exc}") from exc
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(plugins, dict):
        return None
    row = plugins.get(name)
    if not isinstance(row, dict):
        return None
    public = row.get("public_key")
    return public if isinstance(public, str) and public else None


def _pin(home: Path, name: str, public_key: str, key_id: str) -> None:
    path = _pin_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    plugins: dict[str, dict[str, str]] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GalleryError(f"cannot read trusted gallery keys {path}: {exc}") from exc
        raw = payload.get("plugins") if isinstance(payload, dict) else None
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, dict):
                    public = value.get("public_key")
                    stored_id = value.get("key_id")
                    if isinstance(public, str):
                        plugins[key] = {
                            "public_key": public,
                            "key_id": stored_id if isinstance(stored_id, str) else "",
                        }
    plugins[name] = {"public_key": public_key, "key_id": key_id}
    body = {"version": 1, "plugins": plugins}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_secret(path: Path) -> SecretKey:
    """Read an unencrypted minisign secret key."""
    try:
        return load_secret_key(path.read_text(encoding="utf-8"))
    except MinisignError as exc:
        raise GalleryError(str(exc)) from exc
    except OSError as exc:
        raise GalleryError(f"cannot read secret key {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file, used when printing a bundle digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
