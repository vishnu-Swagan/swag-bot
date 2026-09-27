"""Taint firewall for tool output.

Every span that enters the agent is labeled with a source and a trust level.
The user goal is trusted. Web pages, MCP tool results, plugin output, and
file contents from outside the workspace are untrusted. Labels move by
copying: if a sink argument appears in an untrusted span and not in the
trusted goal, the action is tainted. After any untrusted span has been seen,
a network, destructive, credential, or send action whose target is not in
the trusted goal is tainted too.

That second rule is conservative on purpose. The model can paraphrase, and
this tracker does not see attention weights. It will escalate some actions
a person might have wanted. It will also miss tricks that never put the
target in a tracked span and that still look grounded. ``docs/TAINT.md``
states those limits.

MCP ``_meta.swag`` may raise a tool's risk, name extra sinks, or name the
source of a result (``web``, ``mcp:<server>``). It cannot mark that result
trusted. A server is not a source of trust.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from swag_bot.config import Settings, TaintMode, TaintReader
from swag_bot.interfaces import (
    SWAG_TAINT_KEY,
    ActionRequest,
    AutonomyLevel,
    LLMClient,
    RiskLevel,
    TaintTracker,
    TrustLevel,
)
from swag_bot.safety.quarantine import (
    LLMQuarantineReader,
    PatternQuarantineReader,
    QuarantineReader,
    unwrap_quarantine,
)

_URL = re.compile(r"https?://[^\s'\"<>)\]]+")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SECRET = re.compile(
    r"(?i)(?:~/?\.ssh|\.ssh/|id_rsa|id_ed25519|(?:^|[\s/\"'])\.env\b|"
    r"credentials|secrets?\.(?:json|txt|yml|yaml)|/\.aws/|\.pem\b)"
)
_OUTSIDE = re.compile(r"(?:~/(?:[^\s'\"|;<>]+)?|/(?:etc|root|home|Users|private)/[^\s'\"|;<>]+)")
_FETCH = re.compile(r"(?i)\b(?:curl|wget|ssh|scp|nc|ncat)\b|https?://")
_DELETE_CMD = re.compile(r"(?i)\b(?:rm|rmdir|unlink|shred|mkfs)\b")
_SEND_CMD = re.compile(
    r"(?i)\b(?:sendmail|msmtp|mailx|mail)\b|\b(?:email|e-mail)\b|\bsend (?:a )?(?:message|mail)\b"
)
_SEND_KIND = re.compile(r"(?i)email|send_message|sendmail|slack")
_REDIRECT = re.compile(r">\s*([^\s;|&<>]+)")

_SINK_NAMES = frozenset({"network", "destructive", "credential", "send"})
_NETWORK_KEYS = frozenset({"url", "uri", "href", "endpoint"})
_SEND_KEYS = frozenset({"to", "recipient", "cc", "bcc"})
_RISK_NAMES = frozenset(level.value for level in RiskLevel)
_SEVERITY = {
    RiskLevel.READ: 0,
    RiskLevel.WRITE: 1,
    RiskLevel.EXECUTE: 2,
    RiskLevel.NETWORK: 3,
    RiskLevel.DESTRUCTIVE: 4,
}

_MAX_SPAN_CHARS = 100_000
_MAX_SPANS = 200
_COPY_MIN = 12
_LAUNDER_MIN = 16
_MESSAGE_LIMIT = 500


@dataclass
class _Span:
    text: str
    source: str
    trust: TrustLevel
    haystack: str


def build_taint_tracker(
    settings: Settings,
    *,
    llm: LLMClient | None = None,
) -> TaintTracker | None:
    """Tracker for ``settings.taint``, or None when the firewall is off.

    ``reader = llm`` uses ``llm.complete`` (no tools) when a client is passed.
    With no client it falls back to the strip reader.
    """
    if not settings.taint.enabled or settings.taint.mode is TaintMode.OFF:
        return None
    reader: QuarantineReader
    if settings.taint.reader is TaintReader.LLM and llm is not None:
        reader = LLMQuarantineReader(llm)
    elif settings.taint.reader is TaintReader.STRIP or (
        settings.taint.reader is TaintReader.LLM and llm is None
    ):
        reader = PatternQuarantineReader(strip=True)
    else:
        reader = PatternQuarantineReader(strip=False)
    return SpanTaintTracker(
        mode=settings.taint.mode.value,
        autonomy=settings.autonomy,
        workspace=settings.taint.workspace,
        reader=reader,
    )


class SpanTaintTracker:
    """In-memory labels for one run. Safe to share across parallel steps."""

    def __init__(
        self,
        *,
        mode: str = "escalate",
        autonomy: AutonomyLevel = AutonomyLevel.ASK_RISKY,
        workspace: TrustLevel = TrustLevel.TRUSTED,
        reader: QuarantineReader | None = None,
    ) -> None:
        if mode not in {"escalate", "block"}:
            raise ValueError("taint mode must be escalate or block")
        self._mode = mode
        self._autonomy = autonomy
        self._workspace = workspace
        self._reader = reader if reader is not None else PatternQuarantineReader(strip=False)
        self._lock = threading.Lock()
        self._spans: list[_Span] = []
        self._tool_meta: dict[str, dict[str, Any]] = {}
        self._tainted_paths: set[str] = set()

    def note(self, text: str, *, source: str, trust: TrustLevel) -> None:
        """Record text that entered the agent."""
        with self._lock:
            self._remember(text, _clean_source(source), trust)

    def register_tool(self, name: str, meta: Mapping[str, Any]) -> None:
        """Store a cleaned ``_meta.swag`` object for ``name``."""
        with self._lock:
            self._tool_meta[name] = _clean_meta(meta)

    def prepare(self, action: ActionRequest, *, tool: str) -> ActionRequest:
        """Drop a forged stamp, maybe raise risk, and stamp tainted sinks."""
        with self._lock:
            return self._prepare(action, tool=tool)

    def label_output(self, tool: str, arguments: Mapping[str, Any], output: str) -> str:
        """Record ``output`` and quarantine it when it is untrusted."""
        with self._lock:
            raw, source, trust = self._record_output(tool, arguments, output, None)
        if trust is TrustLevel.UNTRUSTED:
            return self._reader.present(raw, source=source)
        return raw

    def observe_result(
        self,
        tool: str,
        output: str,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        """Record an MCP result. The caller may still return the raw text."""
        with self._lock:
            self._record_output(tool, {}, output, meta)

    def _prepare(self, action: ActionRequest, *, tool: str) -> ActionRequest:
        clean = {key: value for key, value in action.arguments.items() if key != SWAG_TAINT_KEY}
        raised = _raise_risk(action.risk, self._tool_meta.get(tool, {}))
        base = action.model_copy(update={"arguments": clean, "risk": raised})
        stamp = self._assess(base, tool)
        if stamp is None:
            return base
        stamped = dict(clean)
        stamped[SWAG_TAINT_KEY] = stamp
        return base.model_copy(update={"arguments": stamped})

    def _assess(self, action: ActionRequest, tool: str) -> dict[str, Any] | None:
        sinks = self._sinks(action, tool)
        if not sinks:
            return None
        structural = _structural_tokens(action)
        command = _command_of(action, tool)
        copied_sources: list[str] = []
        copied_command = bool(command) and self._untrusted_only(command)
        if copied_command:
            copied_sources.extend(self._sources_containing(command))
        for token in structural:
            if self._untrusted_only(token):
                copied_sources.extend(self._sources_containing(token))
        for value in _long_strings(action.arguments):
            if value == command:
                continue
            if self._untrusted_only(value):
                copied_sources.extend(self._sources_containing(value))

        grounded = [token for token in structural if self._in(token, TrustLevel.TRUSTED)]
        unknown = [
            token
            for token in structural
            if not self._in(token, TrustLevel.TRUSTED) and not self._in(token, TrustLevel.UNTRUSTED)
        ]
        sources = _dedupe(copied_sources)
        if sources:
            reason = (
                "The action copies a command or sink target from untrusted data "
                "that is not in the trusted user goal."
            )
            return self._stamp(tool, sinks, sources, reason)
        if structural and len(grounded) == len(structural) and not copied_command:
            return None
        if command and self._in(command, TrustLevel.TRUSTED):
            return None
        if self._saw_untrusted() and (unknown or not structural):
            reason = (
                "This sink's target is not in the trusted user goal, and the "
                "model has already seen untrusted data."
            )
            return self._stamp(tool, sinks, self._untrusted_sources(), reason)
        return None

    def _stamp(
        self,
        tool: str,
        sinks: set[str],
        sources: list[str],
        reason: str,
    ) -> dict[str, Any]:
        shown = sources[:8] or ["untrusted"]
        ordered = sorted(sinks)
        if len(ordered) == 1:
            sink_text = f"a {ordered[0]} action"
        else:
            sink_text = " or ".join(ordered) + " actions"
        source_text = ", ".join(shown)
        message = (
            f"Taint firewall: untrusted data ({source_text}) cannot by itself "
            f"drive {sink_text}. {reason}"
        )
        if len(message) > _MESSAGE_LIMIT:
            message = message[: _MESSAGE_LIMIT - 3] + "..."
        return {
            "tainted": True,
            "tool": tool,
            "sinks": sorted(sinks),
            "sources": shown,
            "reason": reason,
            "enforcement": self._enforcement(),
            "message": message,
        }

    def _enforcement(self) -> str:
        if self._mode == "block" or self._autonomy is AutonomyLevel.AUTO:
            return "deny"
        return "prompt"

    def _sinks(self, action: ActionRequest, tool: str) -> set[str]:
        meta = self._tool_meta.get(tool, {})
        sinks: set[str] = set()
        declared = meta.get("sinks")
        if isinstance(declared, list):
            sinks.update(item for item in declared if isinstance(item, str))
        if meta.get("risk") == RiskLevel.NETWORK.value:
            sinks.add("network")
        if meta.get("risk") == RiskLevel.DESTRUCTIVE.value:
            sinks.add("destructive")
        if action.risk is RiskLevel.NETWORK:
            sinks.add("network")
        if action.risk is RiskLevel.DESTRUCTIVE:
            sinks.add("destructive")
        kind = action.kind.lower()
        if kind in {"network", "http", "fetch"}:
            sinks.add("network")
        if kind in {"email", "send_message", "message"} or _SEND_KIND.search(tool):
            sinks.add("send")
            sinks.add("network")
        if kind in {"delete", "unlink"}:
            sinks.add("destructive")
        permission = action.arguments.get("permission")
        if permission == "secrets" or _nested_permission(action.arguments) == "secrets":
            sinks.add("credential")
        command = _command_of(action, tool)
        focus = "\n".join(
            part
            for part in (
                command,
                action.target or "",
                action.summary,
                tool,
                _string_arg(action.arguments, "path"),
            )
            if part
        )
        keys = _argument_keys(action.arguments)
        if _FETCH.search(focus) or keys & _NETWORK_KEYS:
            sinks.add("network")
        if _DELETE_CMD.search(command) or _DELETE_CMD.search(action.summary):
            sinks.add("destructive")
        if _SEND_CMD.search(focus) or keys & _SEND_KEYS:
            sinks.add("send")
        if _SECRET.search(focus):
            sinks.add("credential")
        if command and self._touches_tainted(command):
            sinks.add("network")
            sinks.add("destructive")
        return sinks & _SINK_NAMES

    def _record_output(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        output: str,
        meta: Mapping[str, Any] | None,
    ) -> tuple[str, str, TrustLevel]:
        raw = unwrap_quarantine(output) if output.startswith("<<<SWAG_UNTRUSTED") else output
        source, trust = self._output_label(tool, arguments, meta)
        self._remember(raw, source, trust)
        self._note_side_effects(tool, arguments, trust)
        return raw, source, trust

    def _output_label(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        meta: Mapping[str, Any] | None,
    ) -> tuple[str, TrustLevel]:
        merged = dict(self._tool_meta.get(tool, {}))
        if meta:
            merged.update(_clean_meta(meta))
        source, trust = self._heuristic_output(tool, arguments)
        declared = merged.get("source")
        if isinstance(declared, str) and declared.strip():
            source = _clean_source(declared)
        if merged.get("trust") == TrustLevel.UNTRUSTED.value:
            trust = TrustLevel.UNTRUSTED
        if _forced_untrusted(tool, source):
            trust = TrustLevel.UNTRUSTED
        return source, trust

    def _heuristic_output(
        self,
        tool: str,
        arguments: Mapping[str, Any],
    ) -> tuple[str, TrustLevel]:
        if "__" in tool:
            server = tool.split("__", 1)[0]
            return f"mcp:{server}", TrustLevel.UNTRUSTED
        plugin = arguments.get("plugin")
        if isinstance(plugin, str) and plugin.strip():
            return f"plugin:{plugin.strip()}", TrustLevel.UNTRUSTED
        if tool == "read_file":
            path = _path_of(arguments)
            if path and _norm_path(path) in self._tainted_paths:
                return f"file:{_norm_path(path)}", TrustLevel.UNTRUSTED
            return "workspace", self._workspace
        if tool == "write_file":
            return "workspace", TrustLevel.TRUSTED
        if tool in {"run_shell", "run_command", "shell"}:
            command = _string_arg(arguments, "command")
            if _FETCH.search(command):
                return "web", TrustLevel.UNTRUSTED
            if _OUTSIDE.search(command) or _SECRET.search(command):
                return "file:outside", TrustLevel.UNTRUSTED
            return "workspace", self._workspace
        return f"tool:{tool}", TrustLevel.UNTRUSTED

    def _note_side_effects(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        trust: TrustLevel,
    ) -> None:
        if tool == "write_file":
            content = arguments.get("content")
            path = _path_of(arguments)
            if isinstance(content, str) and path and self._overlaps_untrusted(content):
                self._tainted_paths.add(_norm_path(path))
        if tool in {"run_shell", "run_command", "shell"} and trust is TrustLevel.UNTRUSTED:
            command = _string_arg(arguments, "command")
            for match in _REDIRECT.finditer(command):
                self._tainted_paths.add(_norm_path(match.group(1)))

    def _remember(self, text: str, source: str, trust: TrustLevel) -> None:
        if not text.strip():
            return
        stored = _clip_span(text)
        if any(
            span.text == stored and span.source == source and span.trust is trust
            for span in self._spans
        ):
            return
        if len(self._spans) >= _MAX_SPANS:
            self._spans.pop(0)
        self._spans.append(
            _Span(text=stored, source=source, trust=trust, haystack=_haystack(stored))
        )

    def _in(self, token: str, trust: TrustLevel) -> bool:
        needle = _haystack(token)
        if len(needle) < 4:
            return False
        for span in self._spans:
            if span.trust is trust and needle in span.haystack:
                return True
        return False

    def _untrusted_only(self, token: str) -> bool:
        return self._in(token, TrustLevel.UNTRUSTED) and not self._in(token, TrustLevel.TRUSTED)

    def _sources_containing(self, token: str) -> list[str]:
        needle = _haystack(token)
        if len(needle) < 4:
            return []
        return [
            span.source
            for span in self._spans
            if span.trust is TrustLevel.UNTRUSTED and needle in span.haystack
        ]

    def _untrusted_sources(self) -> list[str]:
        return _dedupe(span.source for span in self._spans if span.trust is TrustLevel.UNTRUSTED)

    def _saw_untrusted(self) -> bool:
        return any(span.trust is TrustLevel.UNTRUSTED for span in self._spans)

    def _touches_tainted(self, command: str) -> bool:
        folded = command.casefold()
        for path in self._tainted_paths:
            if len(path) >= 3 and path.casefold() in folded:
                return True
        return False

    def _overlaps_untrusted(self, content: str) -> bool:
        if len(content) < _LAUNDER_MIN:
            return False
        for span in self._spans:
            if span.trust is not TrustLevel.UNTRUSTED or len(span.text) < _LAUNDER_MIN:
                continue
            if content in span.text or span.text in content:
                return True
            if _window_hit(span.text, content):
                return True
        return False


def _raise_risk(current: RiskLevel, meta: Mapping[str, Any]) -> RiskLevel:
    declared = meta.get("risk")
    if not isinstance(declared, str) or declared not in _RISK_NAMES:
        return current
    level = RiskLevel(declared)
    if _SEVERITY[level] >= _SEVERITY[current]:
        return level
    return current


def _clean_meta(meta: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    risk = meta.get("risk")
    if isinstance(risk, str) and risk in _RISK_NAMES:
        cleaned["risk"] = risk
    trust = meta.get("trust")
    if trust in {TrustLevel.TRUSTED.value, TrustLevel.UNTRUSTED.value}:
        cleaned["trust"] = trust
    source = meta.get("source")
    if isinstance(source, str) and source.strip():
        cleaned["source"] = _clean_source(source)
    sinks = meta.get("sinks")
    if isinstance(sinks, list):
        cleaned["sinks"] = [item for item in sinks if isinstance(item, str) and item in _SINK_NAMES]
    return cleaned


def _clean_source(source: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ".:_/-@" else "_" for ch in source.strip())
    return (cleaned or "untrusted")[:80]


def _forced_untrusted(tool: str, source: str) -> bool:
    """MCP, the web, plugins, and outside files stay untrusted.

    ``_meta.swag.trust = trusted`` must not override that. Workspace reads
    are not in this set; ``taint.workspace`` decides those.
    """
    if "__" in tool:
        return True
    lowered = source.lower()
    if lowered in {"web", "mcp", "plugin"}:
        return True
    return lowered.startswith(("web:", "mcp:", "plugin:", "file:"))


def _command_of(action: ActionRequest, tool: str) -> str:
    found = _first_command(action.arguments)
    if found:
        return found
    nested = action.arguments.get("arguments")
    if isinstance(nested, dict):
        found = _first_command(nested)
        if found:
            return found
    if tool in {"run_shell", "run_command", "shell"} and action.target:
        return " ".join(action.target.split())
    return ""


def _first_command(arguments: Mapping[str, Any]) -> str:
    for key in ("command", "cmd", "script"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _structural_tokens(action: ActionRequest) -> list[str]:
    blob = "\n".join(_all_strings(action.arguments))
    if action.target:
        blob = f"{blob}\n{action.target}"
    tokens: list[str] = []
    tokens.extend(match.group(0).rstrip(".,") for match in _URL.finditer(blob))
    tokens.extend(match.group(0) for match in _EMAIL.finditer(blob))
    tokens.extend(match.group(0) for match in _SECRET.finditer(blob))
    return _dedupe(token for token in tokens if len(token) >= 4)


def _argument_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key != SWAG_TAINT_KEY:
                found.add(key.casefold())
            found.update(_argument_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_argument_keys(item))
    return found


def _all_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        if value.strip():
            found.append(value)
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == SWAG_TAINT_KEY:
                continue
            found.extend(_all_strings(item))
        return found
    if isinstance(value, list):
        for item in value:
            found.extend(_all_strings(item))
    return found


def _long_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        if len(value) >= _COPY_MIN:
            found.append(value)
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == SWAG_TAINT_KEY:
                continue
            found.extend(_long_strings(item))
        return found
    if isinstance(value, list):
        for item in value:
            found.extend(_long_strings(item))
    return found


def _nested_permission(arguments: Mapping[str, Any]) -> str | None:
    nested = arguments.get("arguments")
    if isinstance(nested, dict):
        permission = nested.get("permission")
        if isinstance(permission, str):
            return permission
    return None


def _string_arg(arguments: Mapping[str, Any], key: str) -> str:
    value = arguments.get(key)
    return value if isinstance(value, str) else ""


def _path_of(arguments: Mapping[str, Any]) -> str:
    value = arguments.get("path")
    return value if isinstance(value, str) else ""


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _clip_span(text: str) -> str:
    if len(text) <= _MAX_SPAN_CHARS:
        return text
    half = _MAX_SPAN_CHARS // 2
    return text[:half] + "\n" + text[-half:]


def _window_hit(blob: str, content: str) -> bool:
    if len(blob) < _LAUNDER_MIN:
        return False
    step = 8
    last = min(len(blob) - _LAUNDER_MIN, 4000)
    index = 0
    while index <= last:
        if blob[index : index + _LAUNDER_MIN] in content:
            return True
        index += step
    return False


def _haystack(text: str) -> str:
    """Whitespace-collapsed, case-folded text used for copy checks."""
    return " ".join(text.split()).casefold()


def _dedupe(items: Any) -> list[str]:
    seen: list[str] = []
    for item in items:
        if isinstance(item, str) and item and item not in seen:
            seen.append(item)
    return seen
