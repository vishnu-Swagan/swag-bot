# core

**Owner:** the core agent (plan-do-verify).

**Edit only:** `src/swag_bot/core/` and `tests/core/`.

Read `docs/ARCHITECTURE.md` before touching a shared file. `interfaces.py` changes stay additive. This package does not change `interfaces.py`.

## What lives here

`swag run "<goal>"` plans a task, runs the steps, and checks them.

- `Planner` asks the injected `LLMClient` for a `TaskPlan`. Success criteria are kept in the step instruction (`Success criteria: ...`).
- `StepExecutor` runs one step. It calls tools on the `ToolRegistry`, asks `PermissionPolicy` and `ApprovalPrompter` before each call, and records an `ActionLogEntry`.
- `Verifier` asks the model whether the observation meets the success criteria. A failed check is retried up to `max_attempts`. A verdict with `replan: true` asks the planner for replacement steps, still capped by `max_steps`.
- Uncertainty escalation is off unless `escalation.enabled` or `swag run --escalate` is set. `uncertainty.py` scores a step from cheap signals. A high score asks a clarifying question (`escalation_prompt.py`) and stops if there is no answer. `jury.py` can block an irreversible action. Reversibility names match the undo ledger; `reversibility.py` is the stub used until that classifier is present. See `docs/ESCALATION.md`.
- `PythonWorkflowEngine` runs independent steps with asyncio, up to a concurrency limit. It is the default.
- `GraphBitWorkflowEngine` is optional (`pip install -e ".[graphbit]"`, Apache-2.0). It is detected at runtime. GraphBit validates the dependency graph. Step bodies still run here so permissions and the injected model stay in Swag Bot. If GraphBit is not installed, `--engine graphbit` falls back to Python.

Built-in tools, registered on the `ToolRegistry` and executed through the `Sandbox`:

- `read_file`
- `write_file` (paths must stay in the sandbox workdir)
- `run_shell`

`loop.py` takes collaborators in its constructor. It does not import `models`, `memory`, `safety`, `mcp`, or `plugins`. `cli.py` is the composition root. It calls `build_llm_client`, `build_memory_store`, `build_sandbox`, `build_permission_policy`, and `build_prompter`, selects plugin skills for the goal, recalls memories before planning, registers built-in tools plus MCP tools, and saves the summary to memory afterwards. A factory that still raises `NotImplementedYet` is replaced with a small in-process stand-in, except the model client: a model error fails the run.

The command writes `plan.json`, `action-log.jsonl`, and `summary.md` under `--output-dir` (default `./swag-output/<UTC timestamp>`). `--dry-run` plans only. The terminal shows a live task list (`pending`, `running`, `done`, `failed`, `skipped`) and streams step output.

## CLI

`cli.py` defines `run`. The root app flattens it to `swag run`.
