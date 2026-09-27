# Changelog

All notable changes to Swag Bot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Evidence ledger and execution-grounded checks. Each step can carry acceptance checks (`file_exists`, `file_contains`, `command`, `exit_code`, `json_schema`). The harness runs them and records real tool output in `<output-dir>/run.jsonl`. A step is not done unless that evidence is cited. See `docs/spec/evidence-contract.md`.
- `swag run` appends its actions to `$SWAG_HOME/actions.jsonl`, so `swag safety log` shows the same actions as the run. `--no-evidence` restores model-only checks.
- Undo ledger. Before each file write and each shell command, Swag Bot stores a content-addressed snapshot of the sandbox workdir under `$SWAG_HOME/undo`. `swag undo` restores the latest run. `swag undo --to <step>` restores the start of that step, including files a shell command edited or deleted.
- Reversibility. Actions are `reversible`, `compensable`, or `irreversible`. Plugins and MCP tools can declare an inverse (`compensations` in `plugin.json`, or `swagCompensation` on an MCP tool). Undo runs those inverses in reverse when a callable is registered, and lists irreversible actions it cannot restore.
- Autonomy `ask-irreversible`. Prompts only at the point of no return. The default remains `ask-risky`, which still prompts for writes and shell commands. Irreversible actions are marked in the approval prompt.

## [0.1.0] - 2026-09-27

First tagged release. This is the v0 agent: `swag run` plans a goal, carries
the steps out, and checks its own work.

### Added

- `swag` command-line tool: `run`, `doctor`, `version`, and `serve-mcp`
- Plan-do-verify loop with parallel independent steps, and an optional GraphBit engine that falls back to the Python scheduler
- Local sandbox by default, optional Docker sandbox, permission policy (`ask-always`, `ask-risky`, `auto`), and an append-only action log with secret redaction
- Claude Cowork-compatible plugins, Agent Skills, slash commands, and a marketplace installer. Approving `swag plugin install` writes the requested permissions into `$SWAG_HOME/grants.json`
- MCP client (stdio and streamable HTTP) and `swag serve-mcp` (`swag_run_task`, `swag_list_skills`)
- Models: Ollama by default (no API key); OpenAI, Anthropic, Gemini, and OpenRouter through optional LiteLLM
- Memory: SQLite by default, a JSON file, or an external agentmemory server. A run recalls matching memories before planning and saves a summary after
- Example plugin `plugins/example-github-helper`
- Strict mypy on the `swag_bot` package in CI (Python 3.11 and 3.12), alongside ruff and pytest
- GitHub Release workflow on `v*` tags. PyPI upload stays off unless `PUBLISH_PYPI` is set

[0.1.0]: https://github.com/vishnu-Swagan/swag-bot/releases/tag/v0.1.0
