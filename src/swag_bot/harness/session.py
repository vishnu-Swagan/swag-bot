"""Turn settings and a client into a scaffold and an optional escalation.

``swag run`` calls ``prepare_harness``. When ``model.harness`` is ``auto``
and the client is a test fake, this returns the client unchanged so scripted
tests keep their existing behavior. A real Ollama or LiteLLM client is
probed once, then the loop is given the matching scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass

from swag_bot.config import Settings
from swag_bot.core.prompts import (
    EXECUTOR_SYSTEM_TINY,
    PLANNER_SYSTEM_TINY,
    VERIFIER_SYSTEM_TINY,
)
from swag_bot.core.scaffold import RunScaffold, StepEscalation
from swag_bot.errors import ConfigError, SwagError
from swag_bot.harness.budget import EscalationBudget
from swag_bot.harness.checks import deterministic_precheck
from swag_bot.harness.probe import CapabilityReport, is_probeable, profile_model
from swag_bot.harness.schema import PLAN_SCHEMA, VERDICT_SCHEMA
from swag_bot.harness.sizing import estimate_cost_usd, estimate_seconds, request_timeout_seconds
from swag_bot.harness.tools import make_picker
from swag_bot.interfaces import LLMClient
from swag_bot.models.factory import get_llm_client
from swag_bot.models.litellm_client import LiteLLMClient
from swag_bot.models.ollama import OllamaClient

_SCHEMA_PROVIDERS = frozenset(
    {"ollama", "openai", "anthropic", "gemini", "openrouter", "litellm"}
)


@dataclass(frozen=True)
class _Spec:
    name: str
    max_steps: int | None
    max_tool_rounds: int | None
    max_tools: int | None
    one_tool_per_turn: bool
    short_prompts: bool
    strict_plan: bool
    constrain_json: bool
    deterministic_verify: bool
    guard_repeat_writes: bool
    narrow_tools: bool
    retry_blank_turns: bool


_SPECS: dict[str, _Spec] = {
    "tiny": _Spec(
        name="tiny",
        max_steps=3,
        max_tool_rounds=3,
        max_tools=1,
        one_tool_per_turn=True,
        short_prompts=True,
        strict_plan=True,
        constrain_json=True,
        deterministic_verify=True,
        guard_repeat_writes=True,
        narrow_tools=True,
        retry_blank_turns=True,
    ),
    "standard": _Spec(
        name="standard",
        max_steps=None,
        max_tool_rounds=None,
        max_tools=None,
        one_tool_per_turn=False,
        short_prompts=False,
        strict_plan=False,
        constrain_json=True,
        deterministic_verify=False,
        guard_repeat_writes=False,
        narrow_tools=False,
        retry_blank_turns=False,
    ),
    "frontier": _Spec(
        name="frontier",
        max_steps=None,
        max_tool_rounds=8,
        max_tools=None,
        one_tool_per_turn=False,
        short_prompts=False,
        strict_plan=False,
        constrain_json=True,
        deterministic_verify=False,
        guard_repeat_writes=False,
        narrow_tools=False,
        retry_blank_turns=False,
    ),
}


@dataclass
class PreparedHarness:
    """What ``swag run`` should install for this process."""

    llm: LLMClient
    scaffold: RunScaffold | None
    escalation: StepEscalation | None
    note: str
    report: CapabilityReport | None = None


def prepare_harness(settings: Settings, llm: LLMClient) -> PreparedHarness:
    """Probe when needed and return the scaffold for ``settings.model.harness``."""
    mode = settings.model.harness
    if mode == "off":
        return PreparedHarness(llm=llm, scaffold=None, escalation=None, note="")
    if mode == "auto" and not is_probeable(llm):
        return PreparedHarness(llm=llm, scaffold=None, escalation=None, note="")

    report: CapabilityReport | None = None
    if is_probeable(llm):
        report = profile_model(
            client=llm,
            provider=settings.model.provider,
            model=settings.model.model,
            api_base=settings.model.api_base,
        )
    chosen = mode if mode != "auto" else (report.scaffold if report is not None else "standard")
    if chosen not in _SPECS:
        chosen = "standard"
    schema_ok = _schema_ok(settings, report)
    scaffold = _scaffold(chosen, schema_ok=schema_ok)
    timeout = request_timeout_seconds(
        settings.model.provider,
        settings.model.model,
        settings.model.timeout,
    )
    llm = _apply_timeout(llm, timeout)
    escalation, warning = _escalation(settings)
    note = _note(
        chosen,
        report,
        timeout if _has_timeout(llm) else None,
        escalation.label if escalation is not None else "",
        warning,
    )
    return PreparedHarness(
        llm=llm,
        scaffold=scaffold,
        escalation=escalation,
        note=note,
        report=report,
    )


def _schema_ok(settings: Settings, report: CapabilityReport | None) -> bool:
    if report is not None:
        return report.supports_json_schema
    return settings.model.provider.strip().lower() in _SCHEMA_PROVIDERS


def _scaffold(name: str, *, schema_ok: bool) -> RunScaffold:
    spec = _SPECS[name]
    use_schema = spec.constrain_json and schema_ok
    picker = None
    if spec.narrow_tools:
        picker = make_picker(max_tools=spec.max_tools, one_tool_per_turn=spec.one_tool_per_turn)
    return RunScaffold(
        name=spec.name,
        max_steps=spec.max_steps,
        max_tool_rounds=spec.max_tool_rounds,
        planner_system=PLANNER_SYSTEM_TINY if spec.short_prompts else None,
        executor_system=EXECUTOR_SYSTEM_TINY if spec.short_prompts else None,
        verifier_system=VERIFIER_SYSTEM_TINY if spec.short_prompts else None,
        plan_schema=PLAN_SCHEMA if use_schema else None,
        verdict_schema=VERDICT_SCHEMA if use_schema else None,
        strict_plan=spec.strict_plan,
        pick_tools=picker,
        precheck=deterministic_precheck if spec.deterministic_verify else None,
        guard_repeat_writes=spec.guard_repeat_writes,
        retry_blank_turns=spec.retry_blank_turns,
    )


def _apply_timeout(llm: LLMClient, timeout: float | None) -> LLMClient:
    if timeout is None:
        return llm
    if isinstance(llm, (OllamaClient, LiteLLMClient)):
        llm.timeout = timeout
        return llm
    return llm


def _has_timeout(llm: LLMClient) -> bool:
    return isinstance(llm, (OllamaClient, LiteLLMClient))


def _escalation(settings: Settings) -> tuple[StepEscalation | None, str]:
    fallback = settings.model.fallback
    provider = fallback.provider.strip().lower()
    model = fallback.model.strip()
    if not provider or not model:
        return None, ""
    timeout = request_timeout_seconds(provider, model, settings.model.timeout)
    try:
        client = get_llm_client(
            settings.model_copy(
                update={
                    "model": settings.model.model_copy(
                        update={
                            "provider": provider,
                            "model": model,
                            "api_base": fallback.api_base,
                            "timeout": timeout,
                        }
                    )
                }
            )
        )
    except (ConfigError, SwagError) as exc:
        return None, f"fallback skipped: {exc}"
    budget_settings = settings.model.budget
    budget = EscalationBudget(
        max_escalations=budget_settings.max_escalations,
        max_extra_seconds=budget_settings.max_extra_seconds,
        max_cost_usd=budget_settings.max_cost_usd,
    )
    estimated_seconds = estimate_seconds(provider, model)
    estimated_cost = estimate_cost_usd(provider)

    def allow() -> bool:
        return budget.allow(
            estimated_seconds=estimated_seconds,
            estimated_cost_usd=estimated_cost,
        )

    label = (
        f"{provider}/{model} "
        f"(up to {budget_settings.max_escalations} steps, "
        f"{budget_settings.max_extra_seconds:.0f}s, "
        f"${budget_settings.max_cost_usd:.2f})"
    )
    return (
        StepEscalation(
            llm=client,
            model=model,
            allow=allow,
            charge=budget.charge,
            label=label,
        ),
        "",
    )


def _note(
    scaffold: str,
    report: CapabilityReport | None,
    timeout: float | None,
    fallback: str,
    warning: str,
) -> str:
    if report is None:
        text = f"harness: {scaffold} (no probe)"
    else:
        where = "cached probe" if report.cached else "probed"
        context = "unknown" if report.context_tokens is None else str(report.context_tokens)
        text = (
            f"harness: {scaffold} ({where} {report.provider}/{report.model}, "
            f"json {report.json_adherence:.2f}, tools {report.tool_call_reliability:.2f}, "
            f"context {context})"
        )
    if timeout is not None:
        text += f", request timeout {timeout:.0f}s"
    if fallback:
        text += f", fallback {fallback}"
    if warning:
        text += f", {warning}"
    return text
