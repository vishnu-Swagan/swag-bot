"""Static checks run before a gallery plugin is installed.

The rules are original. They look for patterns that showed up in the 2026
skill-supply-chain incidents: obfuscated execution, ``curl | sh``, credential
paths, and code that does more than ``plugin.json`` declares. This is not a
sandbox and it does not execute the plugin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from swag_bot.plugins.bundle import plugin_files

_MAX_FILE = 512 * 1024
_TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".md",
        ".json",
        ".toml",
        ".yml",
        ".yaml",
        ".txt",
        ".ps1",
        ".rb",
        ".pl",
        ".html",
        ".xml",
        ".ini",
        ".cfg",
        ".env",
        ".command",
    }
)

_CURL_PIPE = re.compile(
    r"(?i)\b(?:curl|wget)\b[^\n]{0,400}\|\s*(?:sudo\s+)?(?:bash|sh|zsh|dash|python3?|perl|ruby)\b"
)
_DECODE_PIPE = re.compile(
    r"(?i)\bbase64\b[^\n]{0,120}(?:-d|--decode)[^\n]{0,80}\|\s*(?:bash|sh|zsh)\b"
)
_EXEC = re.compile(r"(?i)\b(?:eval|exec|compile)\s*\(")
_DECODE = re.compile(
    r"(?i)(?:\bb64decode\b|\batob\s*\(|\bunhexlify\b|codecs\.decode|base64\.decode)"
)
_HEX_RUN = re.compile(r"(?:\\x[0-9a-fA-F]{2}){8,}")
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{160,}={0,2}")
_SENSITIVE_PATH = re.compile(
    r"(?i)(?:~/?\.ssh|\.ssh/|\bid_rsa\b|\bid_ed25519\b|\bid_ecdsa\b|"
    r"\.aws/credentials|\.aws/config|\.netrc\b|\.gnupg/|/etc/shadow)"
)
_EXFIL_SINK = re.compile(
    r"(?i)(?:webhook\.site|discord(?:app)?\.com/api/webhooks|pastebin\.com|"
    r"ngrok(?:-free)?\.(?:io|app)|requestbin|pipedream\.net|hookbin\.com)"
)
_NETWORK = re.compile(
    r"(?i)(?:urllib\.request|urllib\.urlopen|\brequests\.(?:get|post|put|patch|delete|request)\b|"
    r"\bhttpx\.|\bhttp\.client\b|\bsocket\.connect\b|\baxios\b|\bXMLHttpRequest\b|"
    r"\bfetch\s*\(|\bnet\.connect\b|\bcurl\s+https?://|\bwget\s+https?://)"
)
_SHELL = re.compile(
    r"(?i)(?:\bsubprocess\b|\bos\.system\s*\(|\bos\.popen\s*\(|\bchild_process\b|"
    r"shell\s*=\s*True)"
)
_WRITE = re.compile(
    r"(?i)(?:open\s*\([^)\n]{0,160}['\"](?:w|a|x|\+)[^'\"]*['\"]|"
    r"\bwrite_text\s*\(|\bwrite_bytes\s*\()"
)
_ENV = re.compile(r"(?i)(?:\bos\.environ\b|\bos\.getenv\s*\(|\bprocess\.env\b|\bgetenv\s*\()")
_SECRET_NAME = re.compile(
    r"(?i)(?:API_KEY|SECRET_KEY|PRIVATE_KEY|ACCESS_TOKEN|AUTH_TOKEN|PASSWORD)\b"
)
_HARDCODED = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|private[_-]?key)"
    r"['\"\s:=]{1,8}['\"](?!\$\{)[A-Za-z0-9+/=_\-]{20,}['\"]"
)


@dataclass(frozen=True)
class ScanFinding:
    """One static-scan result. ``block`` refuses a gallery install."""

    rule: str
    severity: str
    path: str
    line: int | None
    message: str


def scan_plugin(root: Path, permissions: list[str]) -> list[ScanFinding]:
    """Scan the signed files of ``root`` against the declared permissions."""
    declared = set(permissions)
    findings: list[ScanFinding] = []
    inferred: set[str] = set()
    for path in plugin_files(root):
        relative = path.relative_to(root.expanduser().resolve()).as_posix()
        text = _read_text(path, relative, findings)
        if text is None:
            continue
        _patterns(relative, text, findings, inferred)
    _permissions(declared, inferred, findings)
    findings.sort(key=lambda item: (item.path, item.line or 0, item.rule))
    return findings


def blocking_findings(findings: list[ScanFinding]) -> list[ScanFinding]:
    """Findings that refuse an install unless ``--allow-scan`` is set."""
    return [item for item in findings if item.severity == "block"]


def _read_text(path: Path, relative: str, findings: list[ScanFinding]) -> str | None:
    if path.suffix.lower() not in _TEXT_SUFFIXES and not _shebang(path):
        return None
    size = path.stat().st_size
    if size > _MAX_FILE:
        findings.append(
            ScanFinding(
                rule="scan.skipped-large",
                severity="info",
                path=relative,
                line=None,
                message=f"file is larger than {_MAX_FILE} bytes and was not scanned",
            )
        )
        return None
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _shebang(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def _patterns(
    relative: str,
    text: str,
    findings: list[ScanFinding],
    inferred: set[str],
) -> None:
    _hit(
        findings,
        relative,
        text,
        _CURL_PIPE,
        "shell.curl-pipe",
        "block",
        "remote script piped into a shell",
    )
    if _CURL_PIPE.search(text):
        inferred.update({"shell", "network"})
    _hit(
        findings,
        relative,
        text,
        _DECODE_PIPE,
        "shell.decode-pipe",
        "block",
        "decoded bytes piped into a shell",
    )
    if _DECODE_PIPE.search(text):
        inferred.add("shell")
    if _encoded_exec(text):
        findings.append(
            ScanFinding(
                rule="obfuscation.exec-encoded",
                severity="block",
                path=relative,
                line=_line_of(text, _first(_EXEC, text)),
                message="dynamic execution of decoded or hex-escaped bytes",
            )
        )
    _hit(
        findings,
        relative,
        text,
        _B64_BLOB,
        "obfuscation.base64-blob",
        "warn",
        "long base64 literal",
    )
    _hit(
        findings,
        relative,
        text,
        _SENSITIVE_PATH,
        "credentials.sensitive-path",
        "block",
        "reads a credential or key path",
    )
    if _SENSITIVE_PATH.search(text):
        inferred.add("secrets")
    _hit(
        findings,
        relative,
        text,
        _EXFIL_SINK,
        "exfil.sink",
        "block",
        "sends data to a known exfiltration endpoint",
    )
    if _EXFIL_SINK.search(text):
        inferred.add("network")
    if _HARDCODED.search(text):
        findings.append(
            ScanFinding(
                rule="credentials.hardcoded",
                severity="block",
                path=relative,
                line=_line_of(text, _first(_HARDCODED, text)),
                message="hard-coded credential",
            )
        )
        inferred.add("secrets")
    if _NETWORK.search(text):
        inferred.add("network")
    if _SHELL.search(text):
        inferred.add("shell")
    if _WRITE.search(text):
        inferred.add("write")
    if _ENV.search(text) or _SECRET_NAME.search(text):
        inferred.add("secrets")


def _permissions(
    declared: set[str],
    inferred: set[str],
    findings: list[ScanFinding],
) -> None:
    checks = (
        ("network", "network", "permissions.undeclared-network", "uses the network"),
        ("secrets", "secrets", "permissions.undeclared-secrets", "reads credentials"),
        ("shell", "shell", "permissions.undeclared-shell", "runs shell commands"),
        ("write", "filesystem.write", "permissions.undeclared-write", "writes files"),
    )
    for capability, permission, rule, message in checks:
        if capability in inferred and permission not in declared:
            findings.append(
                ScanFinding(
                    rule=rule,
                    severity="block",
                    path="plugin.json",
                    line=None,
                    message=f"{message} without declaring {permission}",
                )
            )
        elif permission in declared and capability not in inferred:
            findings.append(
                ScanFinding(
                    rule=f"permissions.unused-{capability}",
                    severity="info",
                    path="plugin.json",
                    line=None,
                    message=f"declares {permission} but no matching code was found",
                )
            )
    if "secrets" in declared and "network" in declared:
        findings.append(
            ScanFinding(
                rule="permissions.broad-combo",
                severity="warn",
                path="plugin.json",
                line=None,
                message="declares both secrets and network, which can exfiltrate credentials",
            )
        )


def _encoded_exec(text: str) -> bool:
    lines = text.splitlines()
    for index, _line in enumerate(lines):
        window = "\n".join(lines[index : index + 6])
        if _EXEC.search(window) and (_DECODE.search(window) or _HEX_RUN.search(window)):
            return True
    return False


def _hit(
    findings: list[ScanFinding],
    relative: str,
    text: str,
    pattern: re.Pattern[str],
    rule: str,
    severity: str,
    message: str,
) -> None:
    match = pattern.search(text)
    if match is None:
        return
    findings.append(
        ScanFinding(
            rule=rule,
            severity=severity,
            path=relative,
            line=_line_of(text, match.start()),
            message=message,
        )
    )


def _first(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text)
    return 0 if match is None else match.start()


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1
