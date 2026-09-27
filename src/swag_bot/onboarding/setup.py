"""``swag setup --auto`` and the quiet first run inside ``swag run``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from swag_bot.config import Settings, config_path, load_settings, save_settings
from swag_bot.errors import SwagError
from swag_bot.onboarding.detect import (
    PROBE_TIMEOUT_SECONDS,
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
ChooseFn = Callable[[str], str]
SecretFn = Callable[[str], str]
EchoFn = Callable[[str], None]
Opener = Callable[[str, float], bytes | None]


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
    base_url: str | None = None,
    choose: ChooseFn | None = None,
    read_secret: SecretFn | None = None,
    echo: EchoFn | None = None,
    opener: Opener | None = None,
) -> SetupResult:
    """Detect a model and write ``config.toml``.

    A pull happens only after a yes: ``assume_yes``, or ``ask`` when
    ``interactive`` is true. A free-cloud key is read only when
    ``interactive`` is true. Dry-run writes nothing and pulls nothing.
    ``base_url`` probes that OpenAI-compatible server and ignores the rest.
    """
    if base_url is not None and base_url.strip():
        return _configure_base_url(base_url, dry_run=dry_run, opener=opener)
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
    if decision.action == "offer":
        return _offer_cloud(
            decision,
            dry_run=dry_run,
            interactive=interactive,
            choose=choose,
            read_secret=read_secret,
            echo=echo,
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
    save_model(decision.provider, decision.model, api_base=decision.api_base)
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


def save_model(provider: str, model: str, api_base: str | None = None) -> None:
    """Update the model section and keep every other setting.

    ``api_base`` is set for a local OpenAI-compatible server and cleared
    for Ollama and for a cloud provider.
    """
    current = load_settings()
    updated = current.model.model_copy(
        update={"provider": provider, "model": model, "api_base": api_base}
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


def _configure_base_url(base_url: str, *, dry_run: bool, opener: Opener | None) -> SetupResult:
    """Point LiteLLM at one OpenAI-compatible server. Do not fall through."""
    from swag_bot.onboarding.local_servers import (
        choose_local_model,
        normalize_base_url,
        probe_openai_models,
    )
    from swag_bot.onboarding.probe_hook import unknown_size_note

    try:
        base = normalize_base_url(base_url)
    except ValueError as exc:
        raise SwagError(str(exc)) from exc
    ids = probe_openai_models(base, timeout=PROBE_TIMEOUT_SECONDS, opener=opener)
    if ids is None:
        raise SwagError(
            f"No OpenAI-compatible server answered at {base}/models. "
            "Start the server, or pick another --base-url."
        )
    picked = choose_local_model(ids)
    if picked is None:
        raise SwagError(
            f"{base} answered, but every model id that states a size is under 7B. "
            "Those models are not selected."
        )
    model_id, known = picked
    litellm_model = "openai/" + model_id
    note = "" if known else unknown_size_note(model_id)
    message = (
        f"Using {base}, model {litellm_model}, through LiteLLM's OpenAI-compatible route. "
        "Prompts stay on this machine." + note
    )
    if dry_run:
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=0,
            provider="litellm",
            model=litellm_model,
            message="Dry run. " + message,
        )
    save_model("litellm", litellm_model, api_base=base)
    return SetupResult(
        wrote_config=True,
        pulled=False,
        exit_code=0,
        provider="litellm",
        model=litellm_model,
        message=message,
    )


def _offer_cloud(
    decision: Decision,
    *,
    dry_run: bool,
    interactive: bool,
    choose: ChooseFn | None,
    read_secret: SecretFn | None,
    echo: EchoFn | None,
) -> SetupResult:
    """Show the free-cloud menu. Ask for a key only in an interactive session."""
    if dry_run:
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=0,
            provider="",
            model="",
            message="Dry run. " + decision.message,
        )
    if not interactive or choose is None or read_secret is None:
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=2,
            provider="",
            model="",
            message=(
                decision.message + "\nRe-run `swag setup --auto` in a terminal to enter a key. "
                "Nothing was written."
            ),
        )
    if echo is not None:
        echo(decision.message)
    from swag_bot.onboarding.free_cloud import provider_by_menu_id
    from swag_bot.onboarding.secrets import save_provider_key

    raw = choose("Provider number or name (blank to skip): ")
    if not raw.strip():
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=2,
            provider="",
            model="",
            message="No provider chosen. Nothing was saved.",
        )
    item = provider_by_menu_id(raw)
    if item is None:
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=2,
            provider="",
            model="",
            message="Unknown provider. Nothing was saved.",
        )
    secret = read_secret(f"{item.env_var} (input is hidden): ")
    if not secret.strip():
        return SetupResult(
            wrote_config=False,
            pulled=False,
            exit_code=2,
            provider="",
            model="",
            message="No key entered. Nothing was saved.",
        )
    try:
        path = save_provider_key(item.env_var, secret)
    except ValueError as exc:
        raise SwagError(str(exc)) from exc
    save_model(item.provider, item.model, api_base=None)
    return SetupResult(
        wrote_config=True,
        pulled=False,
        exit_code=0,
        provider=item.provider,
        model=item.model,
        message=(
            f"Saved {item.env_var} to {path} (mode 0600) and selected {item.model}. "
            f"You can also export {item.env_var} yourself. The key is not printed. "
            f"Prompts are sent to {item.title}. Limits: {item.limits_url}"
        ),
    )


def default_settings_note() -> str:
    """Short line used when setup has not written a file yet."""
    settings = Settings()
    return f"defaults: provider {settings.model.provider}, model {settings.model.model}"
