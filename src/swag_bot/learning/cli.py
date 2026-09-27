"""``swag skill learn|candidates|promote|reject|recheck``.

Registered onto the existing ``skill`` app from the root CLI so this package
does not edit the plugins command module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from swag_bot.config import load_settings, swag_home
from swag_bot.learning.adapters import (
    evidence_source_for,
    install_evidence,
    install_replay,
    replayer_for,
)
from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.protocols import CompletedRun
from swag_bot.learning.records import CandidateRecord
from swag_bot.learning.service import (
    learn_from_run,
    list_candidates,
    promote_candidate,
    recheck_skill,
    reject_candidate,
)


def register_skill_commands(skill_app: typer.Typer) -> None:
    """Add learning commands to ``swag skill``. Safe to call once."""
    if getattr(skill_app, "_swag_skill_learning", False):
        return
    setattr(skill_app, "_swag_skill_learning", True)
    skill_app.command("learn")(learn_cmd)
    skill_app.command("candidates")(candidates_cmd)
    skill_app.command("promote")(promote_cmd)
    skill_app.command("reject")(reject_cmd)
    skill_app.command("recheck")(recheck_cmd)


def learn_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Run JSON. A plan.json written by swag run works."),
    ],
    evidence: Annotated[
        Path | None,
        typer.Option(
            "--evidence",
            help="Evidence JSON for this run (feature #1 schema). "
            "Copied to $SWAG_HOME/evidence/<run_id>.json.",
        ),
    ] = None,
    replay: Annotated[
        Path | None,
        typer.Option(
            "--replay",
            help="Replay outcome JSON (feature #10 schema). "
            "Copied to $SWAG_HOME/replays/<run_id>.json.",
        ),
    ] = None,
) -> None:
    """Distill a succeeded run into a quarantined skill. Promotion stays gated."""
    try:
        run = _load_run(path)
        home = swag_home()
        if evidence is not None:
            install_evidence(home, run.id, evidence)
        if replay is not None:
            install_replay(home, run.id, replay)
        settings = load_settings()
        result = learn_from_run(
            run,
            home=home,
            mode=settings.skill_learning.mode,
            evidence=evidence_source_for(home),
            replayer=replayer_for(home),
            replay_task=settings.skill_learning.replay,
        )
    except SkillLearningError as exc:
        _fail(exc)
    if result.candidate is None:
        _fail(SkillLearningError(result.reason))
    candidate = result.candidate
    if result.promoted and result.active_path is not None:
        typer.echo(f"promoted {candidate.skill_name}")
        typer.echo(f"location: {result.active_path}")
        typer.echo(f"source run: {candidate.run_id}")
        if candidate.evidence_ids:
            typer.echo("evidence: " + ", ".join(candidate.evidence_ids))
        return
    typer.echo(f"candidate {candidate.id} quarantined as {candidate.skill_name}")
    typer.echo(f"not active: {result.reason}")


def candidates_cmd(
    all_states: Annotated[
        bool,
        typer.Option("--all", help="Include promoted and rejected candidates."),
    ] = False,
) -> None:
    """List skills waiting in quarantine."""
    try:
        records = list_candidates(swag_home(), include_closed=all_states)
    except SkillLearningError as exc:
        _fail(exc)
    if not records:
        typer.echo("no skill candidates")
        return
    for record in records:
        typer.echo(f"candidate {record.id}")
        typer.echo(f"  status: {record.status.value}")
        typer.echo(f"  skill: {record.skill_name}")
        typer.echo(f"  run: {record.run_id}")
        typer.echo(f"  goal: {record.goal}")
        if record.block_reason:
            typer.echo(f"  reason: {record.block_reason}")


def promote_cmd(
    candidate_id: Annotated[str, typer.Argument(help="Quarantined candidate id.")],
) -> None:
    """Promote a candidate when verification and a replay both passed."""
    try:
        home = swag_home()
        settings = load_settings()
        result = promote_candidate(
            candidate_id,
            home=home,
            evidence=evidence_source_for(home),
            replayer=replayer_for(home),
            replay_task=settings.skill_learning.replay,
        )
    except SkillLearningError as exc:
        typer.echo(f"not promoted: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    candidate = _require_candidate(result.candidate)
    typer.echo(f"promoted {candidate.skill_name}")
    typer.echo(f"location: {result.active_path}")
    typer.echo(f"source run: {candidate.run_id}")
    typer.echo("evidence: " + ", ".join(candidate.evidence_ids))


def reject_cmd(
    candidate_id: Annotated[str, typer.Argument(help="Candidate id to reject.")],
) -> None:
    """Reject a candidate and remove its active skill if one was promoted."""
    try:
        record = reject_candidate(candidate_id, home=swag_home())
    except SkillLearningError as exc:
        _fail(exc)
    typer.echo(f"rejected {record.id}")


def recheck_cmd(
    skill_name: Annotated[str, typer.Argument(help="Active learned skill name.")],
) -> None:
    """Replay a promoted skill again and demote it if that replay fails."""
    try:
        home = swag_home()
        settings = load_settings()
        result = recheck_skill(
            skill_name,
            home=home,
            replayer=replayer_for(home),
            replay_task=settings.skill_learning.replay,
        )
    except SkillLearningError as exc:
        _fail(exc)
    if result.demoted:
        typer.echo(f"demoted {result.skill_name}: {result.reason}")
        return
    typer.echo(f"still active {result.skill_name}: {result.reason}")


def _load_run(path: Path) -> CompletedRun:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillLearningError(f"cannot read {path}: {exc}") from exc
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SkillLearningError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(loaded, dict):
        raise SkillLearningError(f"{path}: JSON value must be an object")
    try:
        return CompletedRun.model_validate(loaded)
    except ValidationError as exc:
        raise SkillLearningError(f"{path}: invalid run ({exc})") from exc


def _require_candidate(record: CandidateRecord | None) -> CandidateRecord:
    if record is None:
        raise SkillLearningError("promotion did not return a candidate")
    return record


def _fail(exc: SkillLearningError) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc
