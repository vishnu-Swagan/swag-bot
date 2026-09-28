"""Real evidence and replay adapters for the skill-learning gate.

``LedgerEvidenceSource`` reads the evidence ledger copied into a run bundle.
``BundleRunReplayer`` replays that bundle. A same-task request uses the
recorded model responses and passes only when the replay matches. A varied
request runs ``request.goal`` on a live model and passes only when every
step is done. With no model, a varied request is ``unavailable``, which is
not a pass.

The bundle location is ``$SWAG_HOME/bundles/<run_id>.json``. After a replay,
``$SWAG_HOME/replays/<run_id>.json`` stores ``outcome`` and ``detail``.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from swag_bot.core.bundle.replay import replay_run
from swag_bot.errors import SwagError
from swag_bot.interfaces import AutonomyLevel, LLMClient
from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.protocols import (
    ReplayOutcome,
    ReplayRequest,
    ReplayResult,
    ReplaySpec,
    VerifiedRunEvidence,
    check_run_id,
)

_DETAIL_LIMIT = 2000


def register_bundle(home: Path, run_id: str, bundle: Path) -> Path:
    """Remember where a recorded bundle lives so a later replay can find it."""
    safe = _safe_run_id(run_id)
    path = bundle_index_path(home, safe)
    payload = {"run_id": safe, "bundle": str(bundle.resolve())}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def bundle_index_path(home: Path, run_id: str) -> Path:
    """``$SWAG_HOME/bundles/<run_id>.json``."""
    return home / "bundles" / f"{_safe_run_id(run_id)}.json"


def resolve_bundle(home: Path, run_id: str) -> Path | None:
    """Directory named by the bundle index, or None when the index is absent."""
    path = home / "bundles" / f"{_safe_run_id(run_id)}.json"
    if not path.is_file():
        return None
    payload = _read_object(path)
    raw = payload.get("bundle", payload.get("path"))
    if not isinstance(raw, str) or not raw.strip():
        raise SkillLearningError(f"{path}: bundle index needs a bundle path")
    return Path(raw)


def request_from_replay_spec(
    spec: ReplaySpec,
    *,
    skill_name: str,
    varied: bool = False,
) -> ReplayRequest:
    """Build a replay request from a skill's ``references/replay.json``."""
    use_varied = varied and bool(spec.varied_goal)
    goal = spec.varied_goal if use_varied and spec.varied_goal is not None else spec.goal
    return ReplayRequest(
        run_id=spec.run_id,
        goal=goal,
        skill_name=skill_name,
        varied=use_varied,
    )


class LedgerEvidenceSource:
    """Evidence for a run, taken from its bundle ledger when one was recorded.

    A drop-in ``$SWAG_HOME/evidence/<run_id>.json`` is used only when no
    bundle index exists. A recorded run is verified when every step is done
    and the ledger cites at least one successful evidence id.
    """

    def __init__(self, home: Path) -> None:
        self._home = home

    def evidence_for(self, run_id: str) -> VerifiedRunEvidence:
        safe = _safe_run_id(run_id)
        bundled = self._from_bundle(safe)
        if bundled is not None:
            return bundled
        from swag_bot.learning.adapters import FileEvidenceSource, evidence_dir

        return FileEvidenceSource(evidence_dir(self._home)).evidence_for(safe)

    def _from_bundle(self, run_id: str) -> VerifiedRunEvidence | None:
        try:
            bundle = resolve_bundle(self._home, run_id)
        except SkillLearningError as exc:
            return VerifiedRunEvidence(
                run_id=run_id,
                verified=False,
                evidence_ids=[],
                detail=str(exc),
            )
        if bundle is None:
            return None
        if not bundle.is_dir():
            return VerifiedRunEvidence(
                run_id=run_id,
                verified=False,
                evidence_ids=[],
                detail="bundle index does not point at a bundle directory",
            )
        return evidence_from_ledger(
            run_id,
            bundle / "evidence" / "run.jsonl",
            manifest_path=bundle / "manifest.json",
        )


class BundleRunReplayer:
    """``RunReplayer`` backed by a recorded run bundle.

    Same-task replays do not call a model. Varied replays call ``llm`` on
    ``request.goal``. ``llm`` may be omitted; a varied request is then
    unavailable rather than passed.
    """

    def __init__(
        self,
        home: Path,
        *,
        llm: LLMClient | None = None,
    ) -> None:
        self._home = home
        self._llm = llm

    def replay(self, request: ReplayRequest) -> ReplayResult:
        if request.varied:
            result = self._varied(request)
        else:
            result = self._same(request)
        if result.detail.startswith("recorded outcome file"):
            return result
        _write_replay(self._home, result)
        return result

    def _same(self, request: ReplayRequest) -> ReplayResult:
        try:
            bundle = resolve_bundle(self._home, request.run_id)
        except SkillLearningError as exc:
            return _result(request, ReplayOutcome.FAILED, str(exc))
        if bundle is None or not bundle.exists():
            return self._file_or_unavailable(request, bundle)
        try:
            with tempfile.TemporaryDirectory(prefix="swag-replay-") as raw:
                report = replay_run(bundle, mode="recorded", workdir=Path(raw))
        except SwagError as exc:
            return _result(request, ReplayOutcome.FAILED, str(exc))
        if report.matched:
            return _result(request, ReplayOutcome.PASSED, "recorded replay matched the bundle")
        detail = "recorded replay did not match"
        if report.differences:
            detail = detail + ": " + "; ".join(report.differences)
        return _result(request, ReplayOutcome.FAILED, detail)

    def _varied(self, request: ReplayRequest) -> ReplayResult:
        if self._llm is None:
            return _result(
                request,
                ReplayOutcome.UNAVAILABLE,
                "no model is configured for a live replay",
            )
        from swag_bot.config import MemorySettings, Settings
        from swag_bot.core.cli import execute_goal

        settings = Settings(
            autonomy=AutonomyLevel.AUTO,
            memory=MemorySettings(mode="off"),
        )
        try:
            with tempfile.TemporaryDirectory(prefix="swag-varied-") as raw:
                destination = Path(raw)
                execute_goal(
                    request.goal,
                    output_dir=destination,
                    client=self._llm,
                    autonomy=AutonomyLevel.AUTO,
                    memory_mode="off",
                    evidence=True,
                    settings=settings,
                    max_steps=8,
                    max_attempts=2,
                    concurrency=1,
                )
                from swag_bot.core.artifacts import artifact_file

                plan_path = artifact_file(destination, "plan.json")
                if not plan_path.is_file():
                    return _result(request, ReplayOutcome.FAILED, "live replay wrote no plan")
                statuses = _step_statuses(plan_path)
        except (OSError, SwagError, SkillLearningError, json.JSONDecodeError) as exc:
            return _result(request, ReplayOutcome.FAILED, str(exc))
        if statuses and all(status == "done" for status in statuses.values()):
            return _result(request, ReplayOutcome.PASSED, "live replay finished every step")
        if not statuses:
            return _result(request, ReplayOutcome.FAILED, "live replay produced no steps")
        pending = ", ".join(
            f"{step_id} {status}" for step_id, status in statuses.items() if status != "done"
        )
        return _result(
            request,
            ReplayOutcome.FAILED,
            f"live replay left steps unfinished: {pending}",
        )

    def _file_or_unavailable(self, request: ReplayRequest, bundle: Path | None) -> ReplayResult:
        from swag_bot.learning.adapters import FileRunReplayer, replay_dir

        recorded = replay_dir(self._home) / f"{request.run_id}.json"
        if recorded.is_file():
            found = FileRunReplayer(replay_dir(self._home)).replay(request)
            return found.model_copy(
                update={"detail": f"recorded outcome file: {found.detail}".strip()}
            )
        if bundle is None:
            detail = f"no bundle index at {bundle_index_path(self._home, request.run_id)}"
        else:
            detail = f"bundle not found: {bundle}"
        return _result(request, ReplayOutcome.UNAVAILABLE, detail)


def evidence_from_ledger(
    run_id: str,
    ledger_path: Path,
    *,
    manifest_path: Path | None = None,
) -> VerifiedRunEvidence:
    """Read ``run.jsonl`` and the bundle manifest into a gate record."""
    statuses = _manifest_statuses(manifest_path) if manifest_path is not None else {}
    if not ledger_path.is_file():
        return VerifiedRunEvidence(
            run_id=run_id,
            verified=False,
            evidence_ids=[],
            detail="evidence ledger is missing",
        )
    header_run, ok_ids, failed_check = _read_ledger(ledger_path)
    if header_run and header_run != run_id:
        return VerifiedRunEvidence(
            run_id=run_id,
            verified=False,
            evidence_ids=[],
            detail="evidence ledger is for a different run",
        )
    done = bool(statuses) and all(status == "done" for status in statuses.values())
    verified = done and bool(ok_ids)
    if verified:
        detail = "evidence ledger cites a finished run"
    elif failed_check and not done:
        detail = "a check failed"
    elif not done:
        detail = "run did not finish every step"
    else:
        detail = "finished run cites no evidence"
    return VerifiedRunEvidence(
        run_id=run_id,
        verified=verified,
        evidence_ids=ok_ids,
        detail=detail,
    )


def _read_ledger(path: Path) -> tuple[str, list[str], bool]:
    header_run = ""
    ok_ids: list[str] = []
    failed_check = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        loaded: Any = json.loads(line)
        if not isinstance(loaded, dict):
            continue
        record = loaded.get("record")
        if record == "header":
            raw_run = loaded.get("run_id")
            if isinstance(raw_run, str):
                header_run = raw_run
            continue
        if record == "evidence":
            evidence = loaded.get("evidence")
            if isinstance(evidence, dict) and evidence.get("ok") is True:
                evidence_id = evidence.get("id")
                if isinstance(evidence_id, str) and evidence_id not in ok_ids:
                    ok_ids.append(evidence_id)
            continue
        if record == "check":
            check = loaded.get("check")
            if isinstance(check, dict) and check.get("passed") is False:
                failed_check = True
    return header_run, ok_ids, failed_check


def _manifest_statuses(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    result = loaded.get("result")
    if not isinstance(result, dict):
        return {}
    raw = result.get("step_status")
    if not isinstance(raw, dict):
        return {}
    statuses: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            statuses[key] = value
    return statuses


def _step_statuses(path: Path) -> dict[str, str]:
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {}
    steps = loaded.get("steps")
    if not isinstance(steps, list):
        return {}
    statuses: dict[str, str] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = step.get("id")
        status = step.get("status")
        if isinstance(step_id, str) and isinstance(status, str):
            statuses[step_id] = status
    return statuses


def _result(request: ReplayRequest, outcome: ReplayOutcome, detail: str) -> ReplayResult:
    return ReplayResult(
        run_id=request.run_id,
        outcome=outcome,
        detail=_clip(detail),
        varied=request.varied,
        goal=request.goal,
    )


def _write_replay(home: Path, result: ReplayResult) -> None:
    path = home / "replays" / f"{result.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"outcome": result.outcome.value, "detail": result.detail}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillLearningError(f"cannot read {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SkillLearningError(f"{path}: JSON value must be an object")
    return loaded


def _safe_run_id(run_id: str) -> str:
    try:
        return check_run_id(run_id)
    except ValueError as exc:
        raise SkillLearningError(str(exc)) from exc


def _clip(text: str) -> str:
    if len(text) <= _DETAIL_LIMIT:
        return text
    return text[: _DETAIL_LIMIT - 3] + "..."
