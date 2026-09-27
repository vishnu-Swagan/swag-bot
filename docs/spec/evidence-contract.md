# Evidence Contract

Version **1.0**. Spec id: `swag-evidence-contract`.

This is an open specification for how a Swag Bot run proves that a step
actually happened. The reference types live in `swag_bot.interfaces`
(`Check`, `CheckResult`, `Evidence`, `RunRecord`, `Step.checks`,
`StepResult.evidence_ids`). The reference runner is `swag_bot.core.checks`
and the reference ledger is `swag_bot.core.evidence`. Both are MIT, same as
the rest of this repository.

Skill learning, replay, and a jury should build on this file instead of
inventing a second log shape.

## What a run stores

Each run writes `<output-dir>/run.jsonl`. One JSON object per line. `record`
says which payload is set:

| `record` | Payload | Meaning |
| --- | --- | --- |
| `header` | `spec`, `version`, `run_id`, `goal` | First line. `spec` is `swag-evidence-contract`, `version` is `1.0`. `run_id` is the plan id. |
| `evidence` | `evidence` | One tool result or one check observation. |
| `action` | `action` | One `ActionLogEntry`, the same object appended to the action log. |
| `check` | `check` | One `CheckResult`. |

`action-log.jsonl` in the same directory is only the action rows, kept so
older readers still work. The home file `$SWAG_HOME/actions.jsonl` is an
index of those same action rows (same `id`s) across runs. `swag safety log`
reads the index. A row's `run_id` is the plan id; `evidence_id` points at
the ledger row for that action when there is one.

Large stdout, stderr, and file bodies are not inlined. They are UTF-8 files
under `<output-dir>/evidence/<id>.stdout`, `.stderr`, and `.content`. The
evidence object carries `stdout_sha256`, `stderr_sha256`, and
`content_sha256` (hex SHA-256 of the stored bytes) plus `stdout_blob`,
`stderr_blob`, and `content_blob` (paths relative to the run directory).
Secrets are redacted before hashing, so the hash is of the stored bytes. A
body longer than 2,000,000 characters is truncated and `truncated` is true.
`preview` is a short redacted excerpt for prompts.

## Evidence object

| Field | Meaning |
| --- | --- |
| `id` | Opaque id, `ev-` plus 12 hex characters in the reference writer. |
| `kind` | `tool` for an executor tool call, `check` for a harness check. |
| `step_id` | Plan step id. |
| `attempt` | 1-based attempt. A retry is judged on its own attempt. |
| `tool` | Tool name when this came from a tool, or `run_shell` when a command check ran. |
| `summary` | Short label, such as `run_shell pytest -q`. |
| `exit_code` | Process exit code when there is one. |
| `path` | File path or the command string. |
| `ok` | Whether this fact supports success. A non-zero exit, a timeout, a denial, an `error:` result, or an unknown tool is not ok. |
| `detail` | One-line explanation. |
| `preview` | Short redacted excerpt. |
| `duration_ms` | Tool runtime when it was measured. |
| `created_at` | UTC timestamp. |

`ok: false` on a tool is not, by itself, a failed step. A check may expect a
non-zero exit. It does mean the harness will not treat that tool row as
proof that the step succeeded.

## Checks

A step's `checks` array is the acceptance test. The planner should emit it.
When the key is missing, the reference planner derives checks from the step
text. An explicit empty array means "no machine check".

| `kind` | Aliases | Required fields | What the harness does |
| --- | --- | --- | --- |
| `file_exists` | `exists` | `path` | The path is a file inside the sandbox workdir. |
| `file_absent` | `absent` | `path` | The path is not a file there. |
| `file_contains` | `contains` | `path`, `contains` | The file's UTF-8 text contains `contains`. |
| `command` | `cmd` | `command` | Run `command` in the sandbox. Pass when the exit code equals `expected_exit` (default 0). Default timeout is 60 seconds; set `timeout` to override. |
| `exit_code` | `exit` | `expected_exit` (default 0) | Do not re-run. Pass when the latest tool evidence for this attempt has that exit code. Fail with "never ran" when there is none. |
| `json_schema` | `json` | `path` | The file parses as JSON. `json_schema` (JSON key `schema` is also accepted) may restrict `type`, `required`, and `properties`. This is a subset, not full JSON Schema. |

Unknown kinds do not reject the plan. That check fails at run time with
`unsupported check kind`.

Paths go through the sandbox. `..`, absolute paths, and symlinks that leave
the workdir fail the check. Command checks go through the same permission
policy as `run_shell`. A denied check fails.

Shorthand the reference planner also recognizes inside the step text, one
per line:

```text
file_exists: report.md
file_contains: summary.md "Total"
file_absent: tmp.lock
cmd: pytest -q exits 0
exit_code: 0
json_schema: out.json
```

Plain phrases `report.md exists` and `report.md contains "Total"` are
derived only when the model did not send a `checks` array.

## How a step becomes done

1. The executor runs tools. Every call is appended to the ledger with the
   real exit code, stdout, and stderr. The executor's later prose is a
   claim, not evidence.
2. The verifier runs the step's checks itself and appends those results.
3. If any check fails, the attempt fails. The model's claim cannot override
   it. `StepResult.evidence_ids` lists the evidence the failure cites, and
   `StepResult.check_results` holds each `CheckResult`.
4. If every check passes, those evidence ids are enough to mark the step
   done, including when the model forgets to cite them. The model may still
   reject the step when something checks cannot see is missing.
5. If the step has no checks, the model is shown the ledger excerpt and must
   return `evidence_ids`. The harness keeps only ids that exist and that are
   ok. It attaches ids of successful tool calls when the model omits them.
   It never invents an id.
6. A pass with no successful tool evidence and no passing check is
   `unverified`, not `done`. A failed tool with no passing check fails the
   step even if the model says it worked.

`done` is the only status that means the step succeeded. `failed` means a
check or a tool contradicted the claim. `unverified` means the model claimed
success and the ledger had nothing to cite. Dependents of a failed or
unverified step are skipped. A run's exit code is non-zero when any step is
failed or unverified.

The verifier's JSON is:

```json
{"passed": true, "reason": "why", "replan": false, "evidence_ids": ["ev-..."]}
```

## Config

`evidence.enabled` in `config.toml` defaults to true. `swag run --no-evidence`
judges the step from the model text alone and does not require citations.
Actions are still written to the ledger and to `$SWAG_HOME/actions.jsonl`.

```toml
[evidence]
enabled = true
```
