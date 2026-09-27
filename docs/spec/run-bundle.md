# Run bundle

Version **1.0**. Spec id: `swag-run-bundle`.

This is an open specification for a portable record of one Swag Bot run.
The reference writer is `swag_bot.core.bundle`. It is MIT, same as the rest
of this repository. Skill tests, bug reports, and a later eval corpus should
use this file instead of inventing a second archive shape.

A bundle is a directory, or a zip of that directory. Either form is valid
input to `swag replay` and `swag bundle inspect`.

## Layout

| Path | Meaning |
| --- | --- |
| `manifest.json` | Versions, model, autonomy, result, and pointers below. |
| `plan.json` | The `TaskPlan` after the run, secrets redacted. |
| `model.jsonl` | Every model request and response, in call order. |
| `tools.jsonl` | Every tool call and the real result. |
| `approvals.jsonl` | Approval prompts and the decision. |
| `actions.jsonl` | Action-log rows, redacted again for the bundle. |
| `events.jsonl` | Loop events, including `plan_fallback` when the planner fell back. |
| `memory.jsonl` | Memory writes and the search hits replay should return. |
| `handoff.jsonl` | One row per step: `depends_on`, status, observation, files, evidence ids, checks. |
| `summary.md` | The run summary, redacted. |
| `files/trees.json` | Before and after workspace trees. |
| `files/diffs.json` | Unified diffs for added, edited, and removed files. |
| `files/objects/<aa>/<rest>` | Redacted file bytes, addressed by SHA-256. |
| `evidence/run.jsonl` | The evidence ledger. See below. |

`manifest.json` fields:

| Field | Meaning |
| --- | --- |
| `spec` | `swag-run-bundle` |
| `version` | `1.0` |
| `swag_version` | Package version that wrote the bundle. |
| `python`, `platform` | Interpreter and OS, for bug reports. |
| `run_id` | Plan id. |
| `goal` | The goal, redacted. |
| `model` | `provider`, `model`, and `api_base` (redacted). |
| `autonomy`, `sandbox_mode`, `memory_backend` | Config used for the run. |
| `max_steps`, `max_attempts`, `concurrency`, `engine`, `dry_run` | Loop settings. Replay uses these. |
| `strict_plan` | `true`, `false`, or `null` when this build does not have the flag yet. |
| `memory_mode` | `ask`, `auto`, `off`, or `null` when it was not recorded. |
| `plan_fallback` | `true` when the planner could not parse a plan and used one fallback step. |
| `planner_context` | Recalled memories and skill instructions that were passed into the planner. Replay passes this same text. |
| `tool_order` | Tool names in registration order. The planner prompt lists them in this order. |
| `redacted` | `true`. Bundles are redacted before they are written. |
| `evidence` | `spec`, `version`, `source` (`run.jsonl` or `synthesized`), and `path`. |
| `undo` | Tree hashes from `$SWAG_HOME/undo` when that ledger has this run. |
| `result.step_status` | Step id to final status. Replay compares against this. |
| `result.summary_sha256` | SHA-256 of the redacted summary. |
| `counts` | Model calls, tool calls, approvals, memory writes. |

Unknown manifest keys are ignored so a newer writer still loads.

## Model calls

Each line of `model.jsonl`:

| Field | Meaning |
| --- | --- |
| `index` | Call order, starting at 0. |
| `kind` | `chat` or `complete`. |
| `model` | Model argument passed into the client. |
| `tools` | Tool names offered on that call. |
| `fingerprint` | SHA-256 of the redacted request. Replay matches on this before falling back to order. |
| `messages` | Redacted chat messages. |
| `response` | Redacted `ChatResponse`. |

## Tools, approvals, handoff, memory

`tools.jsonl` stores `name`, `call_id`, redacted `arguments`, redacted `result`, `step_id`, `attempt`, and `key` (a stable id of the redacted name and arguments).

`approvals.jsonl` stores one object per prompt: `approved` and the redacted `action`. Policy decisions that did not prompt are in `actions.jsonl`.

`handoff.jsonl` is the step-handoff record. Each row has `depends_on` from the plan, the step status, the observation, files that changed during that step, `evidence_ids` when the step result has them, and `checks` when the step has them. Those last two are empty until the evidence ledger and check runner are present. Replay does not require them.

`memory.jsonl` has two operations.

An `add` row stores redacted `content` and `metadata`. If the metadata had no `run_id`, the bundle adds the plan id. It does not change what was written to the memory store. `counts.memory_writes` counts these rows.

A `search` row stores the redacted `query`, `results` (the content strings the store returned), and `phase`. `phase` is `planner` for the recall that built `planner_context`, and `step` for searches during a step. Replay returns `step` results for the same query, in the order they were recorded. It does not serve `planner` rows again.

`events.jsonl` stores `kind`, `step_id`, `status`, and redacted `text`. `kind` `plan_fallback` means the planner used the one-step fallback. The text starts with `PLAN FALLBACK`.

## Files

`files/trees.json` has `before` and `after`. Each side has `tree` (SHA-256 of the canonical entry JSON) and `entries`. A file entry is `{hash, kind, mode, path}`, the same shape as a snapshot in the undo ledger. `hash` is the SHA-256 of the **redacted** UTF-8 bytes. The undo store hashes the original bytes, so the hashes match when redaction changed nothing.

`files/objects/` uses the same `<2 hex chars>/<rest>` layout as `$SWAG_HOME/undo/objects`, under `files/` so the bundle stays self-contained.

`files/diffs.json` lists `add`, `modify`, and `delete` with a unified diff of the redacted text.

Top-level run artifacts (`plan.json`, `action-log.jsonl`, `summary.md`, `run.jsonl`) and the `bundle/`, `evidence/`, and `.git/` directories are not part of the workspace snapshot.

## Evidence ledger

`evidence/run.jsonl` follows the Evidence Contract (`docs/spec/evidence-contract.md`): a `header` line (`spec` `swag-evidence-contract`, `version` `1.0`, `run_id`, `goal`) and then `evidence`, `action`, or `check` lines.

When the run directory already contains `run.jsonl`, the bundle copies that file and sets `evidence.source` to `run.jsonl`. That is the ledger from the evidence work. When the file is absent, the bundle synthesizes a compatible ledger from the tool calls and actions it recorded, and sets `source` to `synthesized`.

## Undo checkpoints

`manifest.undo` is aligned with the undo ledger under `$SWAG_HOME/undo`. `present` is true when `undo/runs/<id>.json` matches the plan id, or the undo index lists a run whose workdir is this run's workdir. The bundle copies `base_tree` and checkpoint tree hashes. It does not copy the undo object store; file bytes in the bundle are the redacted copies above.

## Redaction

Before anything is written, secret-shaped text is replaced with `[REDACTED]`:

- PEM private keys
- `Bearer` tokens
- `sk-` keys, `AKIA` keys, `ghp_` / `github_pat_` tokens
- `password=`, `api_key=`, `token=`, and the same words with a colon
- query-string `token`, `api_key`, `secret`, `password`, `access_token`
- values of keys whose names look like a secret

Redaction is idempotent. Ordinary words are left alone. A replay of a bundle reproduces the redacted trajectory: a file whose contents were a secret is rewritten as `[REDACTED]`, not as the original secret.

## Replay API

```python
from swag_bot.core.bundle import BundleReplayer, replay_run

report = replay_run("path/to/bundle")  # recorded responses, offline
assert report.matched

live = replay_run("path/to/bundle", mode="live", llm=client)
```

`BundleReplayer` implements `RunReplayer`. Skill tests should call `replay_run` or that class. Recorded mode does not call a model. It restores the before-files, passes `planner_context` into the planner, returns recorded step-memory hits for the same query, and returns the saved model response whose fingerprint matches the redacted request. If none matches, it uses the next unused saved response and counts a mismatch. In `tool_mode="recorded"`, tools are registered in `tool_order` so the planner prompt lists them the same way.

`mode="live"` calls the client you pass and compares step status, workspace file hashes, and the summary to the bundle.

`tool_mode="rerun"` (the default) executes tools again. `tool_mode="recorded"` returns the saved tool results and then restores the after-files.

`swag replay <bundle>` is the command. `swag bundle inspect` prints a summary. `swag bundle export -o run.zip <bundle>` zips it. `swag run --record` writes `<output-dir>/bundle`. `--bundle <dir>` chooses the directory. `bundle.record = true` in config records every run.

A replay exits 0 when the new run matches the bundle.
