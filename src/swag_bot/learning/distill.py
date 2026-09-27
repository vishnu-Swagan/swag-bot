"""Distill a successful run into a Cowork-compatible ``SKILL.md``.

The writer does not import the plugin loader. It emits the Agent Skills
frontmatter subset that loader already accepts: a mapping, one nested
mapping, and double-quoted scalars.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from swag_bot.interfaces import SkillMeta
from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.protocols import CompletedRun, ReplaySpec, RunStepRecord, SkillProvenance

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_QUOTED = re.compile(r'"[^"\n]+"|\'[^\'\n]+\'')
_FILE = re.compile(r"(?<![\w.-])[\w.-]+\.[A-Za-z0-9]{1,8}(?![\w.-])")
_CLIP = 500


@dataclass(frozen=True)
class DistilledSkill:
    """A candidate skill that has not been promoted."""

    name: str
    description: str
    body: str
    varied_goal: str | None
    replay_spec: ReplaySpec

    def markdown(self, *, candidate_id: str, provenance: SkillProvenance | None) -> str:
        """Render ``SKILL.md``. Provenance is included only after promotion."""
        return render_skill_markdown(self, candidate_id=candidate_id, provenance=provenance)

    def files(self, *, candidate_id: str, provenance: SkillProvenance | None) -> dict[str, str]:
        """Relative paths written into the skill directory."""
        written = {
            "SKILL.md": self.markdown(candidate_id=candidate_id, provenance=provenance),
            "references/replay.json": self.replay_spec.model_dump_json(indent=2) + "\n",
        }
        if provenance is not None:
            written["references/provenance.json"] = provenance.model_dump_json(indent=2) + "\n"
        return written


def distill(run: CompletedRun) -> DistilledSkill:
    """Turn a succeeded run into a skill. Callers must not pass a failed run."""
    if not run.succeeded():
        raise SkillLearningError("only a succeeded run can be distilled")
    varied = vary_goal(run.goal)
    name = skill_name_for(run.goal, run.id)
    description = description_for(run.goal)
    try:
        SkillMeta(name=name, description=description, license="MIT")
    except ValidationError as exc:
        raise SkillLearningError(f"distilled skill metadata is invalid: {exc}") from exc
    steps = [_clipped_step(step) for step in run.steps]
    spec = ReplaySpec(
        run_id=run.id,
        goal=" ".join(run.goal.split()),
        varied_goal=varied,
        steps=steps,
    )
    body = render_body(run.id, spec.goal, steps, varied)
    return DistilledSkill(
        name=name,
        description=description,
        body=body,
        varied_goal=varied,
        replay_spec=spec,
    )


def vary_goal(goal: str) -> str | None:
    """Replace quoted arguments and filenames so a replay can vary the task.

    Returns None when the goal has nothing concrete to replace.
    """
    flat = " ".join(goal.split())
    count = 0

    def repl_quoted(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "{{arg" + str(count) + "}}"

    varied = _QUOTED.sub(repl_quoted, flat)
    files = 0

    def repl_file(match: re.Match[str]) -> str:
        nonlocal files
        files += 1
        return "{{file" + str(files) + "}}"

    varied = _FILE.sub(repl_file, varied)
    if varied == flat:
        return None
    return varied


def skill_name_for(goal: str, run_id: str) -> str:
    """A directory-safe skill name that includes the source run."""
    slug = re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "learned-task"
    suffix = re.sub(r"[^a-z0-9]", "", run_id.lower())[:12] or "run"
    name = _fit(slug, suffix)
    if _NAME.fullmatch(name) is None:
        name = _fit("learned", suffix)
    return name


def description_for(goal: str) -> str:
    """A discovery description that says when to use the skill. At most 1024 characters."""
    flat = " ".join(goal.split())
    prefix = "Learned procedure. Use when the task is similar to: "
    room = 1024 - len(prefix)
    if len(flat) > room:
        flat = flat[: room - 3].rstrip() + "..."
    text = (prefix + flat).strip()
    if not text:
        return "Learned procedure from a Swag Bot run."
    return text


def render_skill_markdown(
    distilled: DistilledSkill,
    *,
    candidate_id: str,
    provenance: SkillProvenance | None,
) -> str:
    """Cowork-compatible skill file. Metadata values are double-quoted."""
    if provenance is None:
        evidence = "pending"
        status = "candidate"
        replay = "pending"
        source = distilled.replay_spec.run_id
    else:
        evidence = ",".join(provenance.evidence_ids)
        status = "promoted"
        replay = provenance.replay_outcome
        source = provenance.source_run
    lines = [
        "---",
        f"name: {distilled.name}",
        f"description: {yaml_quote(distilled.description)}",
        "license: MIT",
        "compatibility: Distilled by Swag Bot after a verified run and a passing replay.",
        "metadata:",
        "  author: swag-bot",
        '  version: "0.1.0"',
        f"  source-run: {yaml_quote(source)}",
        f"  evidence: {yaml_quote(evidence)}",
        f"  candidate: {yaml_quote(candidate_id)}",
        f"  status: {yaml_quote(status)}",
        f"  replay: {yaml_quote(replay)}",
        "---",
        "",
        distilled.body,
    ]
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


def render_body(
    run_id: str,
    goal: str,
    steps: list[RunStepRecord],
    varied_goal: str | None,
) -> str:
    """Markdown instructions. Frontmatter is not included."""
    lines = [
        f"# {goal}",
        "",
        f"Distilled from run `{run_id}`.",
        "Swag Bot activates this skill only after evidence verification and a passing replay.",
        "",
        "## When to use",
        "",
        goal,
        "",
        "## Steps",
        "",
    ]
    for index, step in enumerate(steps, start=1):
        instruction = step.instruction.strip() or step.title
        lines.append(f"{index}. **{step.title}**")
        lines.append(f"   {instruction}")
        if step.observation.strip():
            lines.append(f"   Observed: {step.observation.strip()}")
        lines.append("")
    lines.extend(["## Parameters", ""])
    if varied_goal:
        lines.append(f"A varied replay replaces concrete names: {varied_goal}")
    else:
        lines.append("Replay the original goal. Nothing concrete was found to vary.")
    lines.extend(
        [
            "",
            "## Replay",
            "",
            f"Replay run `{run_id}` before treating this skill as reliable.",
            "The replay spec is `references/replay.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def yaml_quote(value: str) -> str:
    """Double-quote a scalar for the frontmatter subset this project parses."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _fit(slug: str, suffix: str) -> str:
    name = f"{slug}-{suffix}"
    if len(name) <= 64 and _NAME.fullmatch(name):
        return name
    keep = 64 - len(suffix) - 1
    trimmed = slug[:keep].rstrip("-") if keep > 0 else ""
    if not trimmed:
        trimmed = "learned"
    name = f"{trimmed}-{suffix}"
    if len(name) > 64:
        name = name[:64].rstrip("-")
    return name


def _clipped_step(step: RunStepRecord) -> RunStepRecord:
    return step.model_copy(
        update={
            "instruction": _clip(step.instruction),
            "observation": _clip(step.observation),
            "title": _clip(step.title, limit=200),
        }
    )


def _clip(text: str, limit: int = _CLIP) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    if limit <= 3:
        return flat[:limit]
    return flat[: limit - 3] + "..."
