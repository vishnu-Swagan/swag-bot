"""``swag setup --auto`` and the quiet first run inside ``swag run``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from swag_bot.config import Settings, config_path, load_settings, save_settings
from swag_bot.errors import SwagError
from swag_bot.onboarding.detect import (
    RECOMMENDED_MODEL,
    RECOMMENDED_SIZE_LABEL,
    Decision,
    EnvironmentSnapshot,
    capture_environment,
    decide,
    pull_ollama_model,
)

AskFn = Callable[[str], bool]
ProgressFn = Callable[[str], None]
PullFn = Callable[[str, ProgressFn | None], None]


@dataclass(frozen=True)
class SetupResult:
    """What setup did. ``exit_code`` is 0 when a model is configured."""

    wrote_config: bool
    pulled: bool
    exit_code: int
    provider: str
    model: str
    message: str


def setup_auto(
    *,
    assume_yes: bool = False,
    dry_run: bool = False,
    interactive: bool = False,
    ask: AskFn | None = None,
    progress: ProgressFn | None = None,
    pull: PullFn | None = None,
    snapshot: EnvironmentSnapshot | None = None,
) -> SetupResult:
    """Detect a model and write ``config.toml``.

    A pull happens only after a yes: ``assume_yes``, or ``ask`` when
    ``interactive`` is true. Dry-run writes nothing and pulls nothing.
    """
    facts = capture_environment() if snapshot is None else snapshot
    decision = decide(facts)
    if decision.action == "pull":
        return _pull_and_configure(
            decision,
            assume_yes=assume_yes,
            dry_run=dry_run,
            interactive=interactive,
            ask=ask,
            progress=progress,
            pull=pull,
        )
    if decision.action == "stop":
        message = decision.message
        if dry_run:
            message = "Dry run. " + message
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=2,
            provider=decision.provider,
            model=decision.model,
            message=message,
        )
    if dry_run:
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=0,
            provider=decision.provider,
            model=decision.model,
            message="Dry run. " + decision.message,
        )
    save_model(decision.provider, decision.model)
    return SetupResult(
        wrote_config=True,
        pulled=False,
        exit_code=0,
        provider=decision.provider,
        model=decision.model,
        message=decision.message,
    )


def first_run_if_needed(announce: Callable[[str], None] | None = None) -> None:
    """Configure a model when ``swag run`` has no config file yet.

    This path never asks and never pulls. A missing daemon or a missing key
    leaves the defaults in place so an explicit ``swag run`` still starts.
    """
    if config_path().is_file():
        return
    try:
        result = setup_auto(interactive=False, assume_yes=False, dry_run=False)
    except (OSError, SwagError) as exc:
        if announce is not None:
            announce(f"Setup skipped: {exc}")
        return
    if result.wrote_config and announce is not None:
        announce(result.message)


def save_model(provider: str, model: str) -> None:
    """Update the model section and keep every other setting."""
    current = load_settings()
    updated = current.model.model_copy(
        update={"provider": provider, "model": model, "api_base": None}
    )
    save_settings(current.model_copy(update={"model": updated}))


def _pull_and_configure(
    decision: Decision,
    *,
    assume_yes: bool,
    dry_run: bool,
    interactive: bool,
    ask: AskFn | None,
    progress: ProgressFn | None,
    pull: PullFn | None,
) -> SetupResult:
    question = (
        f"Pull {decision.model} ({RECOMMENDED_SIZE_LABEL})? "
        "This downloads the model from Ollama."
    )
    if dry_run:
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=0,
            provider="ollama",
            model=decision.model,
            message=f"Dry run. {decision.message} Would ask: {question}",
        )
    agreed = assume_yes
    if not agreed and interactive and ask is not None:
        agreed = bool(ask(question))
    if not agreed:
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=2,
            provider="ollama",
            model=decision.model,
            message=(
                f"{decision.message} Not pulled. "
                f"Re-run `swag setup --auto --yes` to pull {RECOMMENDED_MODEL} "
                f"({RECOMMENDED_SIZE_LABEL}), or pull it yourself with "
                f"`ollama pull {RECOMMENDED_MODEL}`."
            ),
        )
    runner = pull if pull is not None else _default_pull
    try:
        runner(decision.model, progress)
    except OSError as exc:
        raise SwagError(str(exc)) from exc
    save_model("ollama", decision.model)
    return SetupResult(
        wrote_config=True,
        pulled=True,
        exit_code=0,
        provider="ollama",
        model=decision.model,
        message=f"Pulled {decision.model} and selected it.",
    )


def _default_pull(name: str, progress: ProgressFn | None) -> None:
    pull_ollama_model(name, on_progress=progress)


def default_settings_note() -> str:
    """Short line used when setup has not written a file yet."""
    settings = Settings()
    return f"defaults: provider {settings.model.provider}, model {settings.model.model}"
