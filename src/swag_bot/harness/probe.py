"""Capability probe: JSON adherence, tool calls, and context size.

The probe runs once per provider and model and is cached under
``$SWAG_HOME/harness/capability.json``. A later run reads the cache instead
of calling the model again. ``swag model probe --force`` refreshes it.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from swag_bot.config import swag_home
from swag_bot.core.parsing import PlanParseError, extract_json
from swag_bot.harness.schema import PROBE_SCHEMA
from swag_bot.harness.sizing import parameter_billions
from swag_bot.interfaces import ChatResponse, LLMClient, Message, Tool
from swag_bot.models.litellm_client import LiteLLMClient
from swag_bot.models.ollama import OllamaClient

PROBE_VERSION = 1
PROBE_REQUEST_TIMEOUT = 20.0

_JSON_PROMPT = (
    "Reply with one JSON object and no other text. "
    "Use exactly two keys: ok and n. "
    "ok is a boolean that is true when two plus two equals four, and false otherwise. "
    "n is an integer equal to two plus two."
)
_TOOL_PROMPT = (
    "Call the echo_token tool. Set token to the word ping. Do not answer in prose."
)
_ECHO = Tool(
    name="echo_token",
    description="Return the token you were given.",
    parameters={
        "type": "object",
        "properties": {"token": {"type": "string"}},
        "required": ["token"],
    },
)
_FRONTIER_MARKERS = (
    "gpt-4",
    "gpt-5",
    "claude",
    "opus",
    "sonnet",
    "gemini-1.5",
    "gemini-2",
    "o1",
    "o3",
)
_SCHEMA_PROVIDERS = frozenset(
    {"ollama", "openai", "anthropic", "gemini", "openrouter", "litellm"}
)


class CapabilityReport(BaseModel):
    """What one probe learned about a model. ``scaffold`` is the profile to use."""

    model_config = ConfigDict(extra="ignore")

    probe_version: int = PROBE_VERSION
    provider: str
    model: str
    json_adherence: float
    tool_call_reliability: float
    tool_call_mode: str
    context_tokens: int | None = None
    supports_json_schema: bool = False
    scaffold: str
    notes: list[str] = Field(default_factory=list)
    probed_at: str = ""
    cached: bool = False


def default_cache_path() -> Path:
    """Where probe results are stored for the current ``SWAG_HOME``."""
    return swag_home() / "harness" / "capability.json"


def cache_key(provider: str, model: str, api_base: str | None) -> str:
    """Identity of a probed model. The version is part of the key."""
    return f"v{PROBE_VERSION}|{provider.strip().lower()}|{model}|{api_base or ''}"


def is_probeable(client: LLMClient) -> bool:
    """True for the real Ollama and LiteLLM clients. Test fakes are not probed."""
    return isinstance(client, (OllamaClient, LiteLLMClient))


def choose_scaffold(
    *,
    model: str,
    json_adherence: float,
    tool_call_reliability: float,
    context_tokens: int | None,
) -> str:
    """Pick ``tiny``, ``standard``, or ``frontier`` from probe scores and the name.

    A model at or under 4B stays on the tiny scaffold even when the short
    probe passes. The 3B failure was on a multi-step file-and-run task, which
    this probe does not fully reproduce, so the size prior still applies.
    """
    size = parameter_billions(model)
    weak_json = json_adherence < 1.0
    weak_tools = tool_call_reliability < 1.0
    if size is not None and size <= 4:
        return "tiny"
    if weak_json:
        return "tiny"
    if weak_tools and (size is None or size < 14):
        return "tiny"
    if context_tokens is not None and context_tokens < 4096:
        return "tiny"
    large = (size is not None and size >= 30) or _looks_frontier(model)
    if large and not weak_tools:
        return "frontier"
    return "standard"


def context_from_show(payload: dict[str, Any] | None) -> int | None:
    """Read a context length from an Ollama ``/api/show`` body."""
    if not payload:
        return None
    info = payload.get("model_info")
    if isinstance(info, dict):
        for key, value in info.items():
            if not str(key).endswith("context_length"):
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value > 0:
                return value
            if isinstance(value, float) and value > 0:
                return int(value)
    parameters = payload.get("parameters")
    if isinstance(parameters, str):
        match = re.search(r"num_ctx\s+(\d+)", parameters)
        if match is not None:
            return int(match.group(1))
    return None


def profile_model(
    *,
    client: LLMClient,
    provider: str,
    model: str,
    api_base: str | None = None,
    force: bool = False,
    cache_path: Path | None = None,
) -> CapabilityReport:
    """Return the cached profile, or probe ``client`` and cache a successful call."""
    path = default_cache_path() if cache_path is None else cache_path
    key = cache_key(provider, model, api_base)
    if not force:
        cached = _load(path, key)
        if cached is not None:
            return cached.model_copy(update={"cached": True})
    try:
        report, cacheable = _probe(client, provider=provider, model=model)
    except Exception as exc:
        report = _heuristic(provider, model, f"probe failed: {exc}")
        cacheable = False
    if cacheable:
        _store(path, key, report)
    return report


def render_report(report: CapabilityReport) -> str:
    """Plain-text profile for ``swag model probe`` and ``swag doctor --probe``."""
    context = "unknown" if report.context_tokens is None else str(report.context_tokens)
    lines = [
        f"model: {report.provider}/{report.model}",
        f"scaffold: {report.scaffold}",
        f"json_adherence: {report.json_adherence:.2f}",
        f"tool_call_reliability: {report.tool_call_reliability:.2f}",
        f"tool_call_mode: {report.tool_call_mode}",
        f"context_tokens: {context}",
        f"supports_json_schema: {str(report.supports_json_schema).lower()}",
        f"cached: {str(report.cached).lower()}",
    ]
    if report.notes:
        lines.append("notes:")
        lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines)


def _probe(
    client: LLMClient,
    *,
    provider: str,
    model: str,
) -> tuple[CapabilityReport, bool]:
    probed = _with_probe_timeout(client)
    notes: list[str] = []
    json_score, schema_ok, json_note, json_down = _probe_json(probed)
    if json_note:
        notes.append(json_note)
    tool_score, tool_mode, tool_note, tool_down = _probe_tools(probed)
    if tool_note:
        notes.append(tool_note)
    context = _probe_context(probed, model)
    if context is None:
        notes.append("context size was not reported by the provider")
    # A timeout is not evidence the model cannot follow JSON. Ignore that
    # score when choosing a scaffold, and do not cache it.
    json_for_choice = 1.0 if json_down else json_score
    tool_for_choice = 1.0 if tool_down else tool_score
    scaffold = choose_scaffold(
        model=model,
        json_adherence=json_for_choice,
        tool_call_reliability=tool_for_choice,
        context_tokens=context,
    )
    if json_down and tool_down:
        notes.append("scaffold chosen from the model name because the probe did not finish")
    report = CapabilityReport(
        provider=provider.strip().lower(),
        model=model,
        json_adherence=json_score,
        tool_call_reliability=tool_score,
        tool_call_mode=tool_mode,
        context_tokens=context,
        supports_json_schema=schema_ok and provider.strip().lower() in _SCHEMA_PROVIDERS,
        scaffold=scaffold,
        notes=notes,
        probed_at=_now(),
    )
    return report, not json_down and not tool_down


def _probe_json(client: LLMClient) -> tuple[float, bool, str, bool]:
    method = getattr(client, "complete_structured", None)
    schema_ok = callable(method)
    try:
        if callable(method):
            response = method([Message.user(_JSON_PROMPT)], PROBE_SCHEMA)
        else:
            response = client.chat([Message.user(_JSON_PROMPT)])
    except Exception as exc:
        if schema_ok and _schema_problem(exc):
            try:
                response = client.chat([Message.user(_JSON_PROMPT)])
            except Exception as inner:
                return 0.0, False, f"json probe failed: {inner}", True
            score, note = _score_json(_text(response))
            return score, False, f"json schema was rejected; {note}", False
        return 0.0, False, f"json probe failed: {exc}", True
    if not isinstance(response, ChatResponse):
        return 0.0, schema_ok, "json probe returned an unexpected response", True
    score, note = _score_json(_text(response))
    return score, schema_ok, note, False


def _probe_tools(client: LLMClient) -> tuple[float, str, str, bool]:
    try:
        response = client.chat([Message.user(_TOOL_PROMPT)], tools=[_ECHO])
    except Exception as exc:
        return 0.0, "none", f"tool probe failed: {exc}", True
    if not isinstance(response, ChatResponse):
        return 0.0, "none", "tool probe returned an unexpected response", True
    calls = response.message.tool_calls
    if not calls:
        return 0.0, "none", "model did not call echo_token", False
    call = calls[0]
    token = call.arguments.get("token")
    if call.name == _ECHO.name and token == "ping":
        return 1.0, "called", "tool call matched", False
    return 0.0, "none", f"unexpected tool call {call.name}", False


def _probe_context(client: LLMClient, model: str) -> int | None:
    show = getattr(client, "show_model", None)
    if not callable(show):
        return None
    try:
        payload = show(model)
    except Exception:
        return None
    if isinstance(payload, dict):
        return context_from_show(payload)
    return None


def _score_json(text: str) -> tuple[float, str]:
    try:
        payload = extract_json(text)
    except PlanParseError:
        return 0.0, "response was not JSON"
    if not isinstance(payload, dict):
        return 0.0, "JSON was not an object"
    ok = payload.get("ok")
    number = payload.get("n")
    if ok is True and _is_int(number, 4):
        return 1.0, "json object matched"
    if "ok" in payload and "n" in payload:
        return 0.5, "json object had the right keys and wrong values"
    return 0.25, "json object was missing ok or n"


def _heuristic(provider: str, model: str, reason: str) -> CapabilityReport:
    scaffold = choose_scaffold(
        model=model,
        json_adherence=1.0,
        tool_call_reliability=1.0,
        context_tokens=None,
    )
    return CapabilityReport(
        provider=provider.strip().lower(),
        model=model,
        json_adherence=0.0,
        tool_call_reliability=0.0,
        tool_call_mode="none",
        supports_json_schema=provider.strip().lower() in _SCHEMA_PROVIDERS,
        scaffold=scaffold,
        notes=[reason, "scaffold chosen from the model name because the probe did not finish"],
        probed_at=_now(),
    )


def _with_probe_timeout(client: LLMClient) -> LLMClient:
    """A copy that gives up quickly so a stuck model does not block the run."""
    if isinstance(client, OllamaClient):
        return OllamaClient(
            model=client.model,
            base_url=client.base_url,
            timeout=PROBE_REQUEST_TIMEOUT,
            transport=client._transport,
        )
    if isinstance(client, LiteLLMClient):
        return LiteLLMClient(
            provider=client.provider,
            model=client.model,
            api_base=client.api_base,
            timeout=PROBE_REQUEST_TIMEOUT,
            completion_fn=client._completion_fn,
        )
    return client


def _load(path: Path, key: str) -> CapabilityReport | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        return None
    item = profiles.get(key)
    if not isinstance(item, dict):
        return None
    if item.get("probe_version") != PROBE_VERSION:
        return None
    try:
        return CapabilityReport.model_validate(item)
    except ValueError:
        return None


def _store(path: Path, key: str, report: CapabilityReport) -> None:
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict) and isinstance(loaded.get("profiles"), dict):
            existing = dict(loaded["profiles"])
    existing[key] = report.model_dump(mode="json", exclude={"cached"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"profiles": existing}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _looks_frontier(model: str) -> bool:
    text = model.lower()
    return any(marker in text for marker in _FRONTIER_MARKERS)


def _schema_problem(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(hint in text for hint in ("format", "schema", "response_format", "unsupported"))


def _text(response: ChatResponse) -> str:
    return response.message.content or ""


def _is_int(value: Any, expected: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value == expected


def _now() -> str:
    return datetime.now(UTC).isoformat()
