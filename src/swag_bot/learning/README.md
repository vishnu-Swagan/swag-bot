# learning

Verification-gated skill learning. Owned by this package so the plan-do-verify
loop, the executor, and the plugins loader stay untouched.

## What it does

A succeeded run is distilled into an Agent Skills `SKILL.md` (the same
frontmatter the plugin loader already accepts). The file is written under
`$SWAG_HOME/skill-candidates/<id>/` and is not an active skill. Standalone
discovery only scans `$SWAG_HOME/skills/` and `.agents/skills/`.

`swag skill promote` copies it into `$SWAG_HOME/skills/<name>/` only when both
of these are true:

1. The run passed evidence-based verification: `verified` is true and at
   least one evidence id is cited. A bare pass with no evidence stays unverified.
2. A replay of the skill on the same task, or on a varied task when
   `skill_learning.replay = "varied"`, returns `passed`.

`swag skill reject` drops the candidate and any active copy. `swag skill recheck`
demotes a promoted skill when a later replay fails. An unavailable replay does
not demote.

Promoted skills record provenance in `SKILL.md` metadata (`source-run`,
`evidence`) and in `references/provenance.json`.

## Config

```toml
[skill_learning]
mode = "review"   # off | review | auto
replay = "same"   # same | varied
```

`review` (the default) quarantines until `swag skill promote`. `auto` promotes
during `swag skill learn` when the gate passes. `off` does not distill.
Explicit `promote` still runs the gate.

## Commands

```text
swag skill learn plan.json [--evidence evidence.json] [--replay replay.json]
swag skill candidates [--all]
swag skill promote CANDIDATE_ID
swag skill reject CANDIDATE_ID
swag skill recheck SKILL_NAME
```

`plan.json` from `swag run` is a valid run file. Learning is not hooked into
`swag run` itself, so this branch does not edit the core loop.

## How #1 and #10 connect

This package does not implement the evidence ledger or run bundles. It defines
two protocols in `protocols.py`:

- `RunEvidenceSource.evidence_for(run_id) -> VerifiedRunEvidence`
- `RunReplayer.replay(request) -> ReplayResult`

Until those features land, the stubs never report a pass. Drop-in files use
the same schemas:

`$SWAG_HOME/evidence/<run_id>.json`

```json
{"run_id": "run-1", "verified": true, "evidence_ids": ["ev-1"], "detail": "checks cited the ledger"}
```

`$SWAG_HOME/replays/<run_id>.json`

```json
{"outcome": "passed", "detail": "replayed the recorded bundle"}
```

`verified: true` with an empty `evidence_ids` list is not accepted. A missing
file is unverified or unavailable, never a pass.

When #1 lands, implement `RunEvidenceSource` against the ledger (or write the
JSON above). When #10 lands, implement `RunReplayer` so `replay()` actually
re-executes `request.goal` and honors `request.varied`. The file adapter is
only a recorded outcome; it does not re-run the task. The candidate's
`references/replay.json` is the replay spec (goal, varied goal, steps) for
that runner.
