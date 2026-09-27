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
- Taint firewall for tool output. Web pages, MCP results, plugin output, and files from outside the workspace are labeled untrusted. Those labels cannot by themselves drive network, destructive, credential, or send actions. `swag run --taint-mode escalate|block|off`. See `docs/TAINT.md`.
- Opt-in uncertainty escalation (`escalation.enabled`, or `swag run --escalate`). An uncertain step asks a specific question and stops if you do not answer. Irreversible actions can require a small jury. A single local model is enough. The jury uses `safety.reversibility`. See `docs/ESCALATION.md`.
- Small-model harness. `swag model probe` and `swag doctor --probe` profile the active model (JSON adherence, tool calls, context size) and cache the result. `swag run` adapts prompts, tool exposure, and plan checks to that profile, and can escalate a failing step to `model.fallback` inside `model.budget`. Ollama request timeouts rise above 120 seconds for local models unless `model.timeout` is set.
- One command to install and run a task: `scripts/install.sh` (and `scripts/install.ps1`), plus `uvx` / pipx instructions that install from Git until `PYPI_PUBLISHED` is flipped
- `swag setup --auto` detects a bring-your-own-key environment variable, a local Ollama model, or a running OpenAI-compatible server (LM Studio, Jan, llama.cpp / llamafile, GPT4All, or `--base-url`). It asks before pulling `qwen2.5:7b` (about 4.7 GB). A 3B-only install is not treated as ready. When nothing local is found it can store a free-plan key (Gemini, Groq, OpenRouter, Cerebras, Mistral) in a mode-0600 file. See `docs/MODELS.md`
- `swag doctor --json` prints a readiness report with `ready` and does not include secret values
- `swag install-mcp` prints the Claude Code command, the Cursor and VS Code install links, and the Gemini, Claude Desktop, and ChatGPT notes
- Claude marketplace entry, Gemini CLI extension manifest, and a Claude Desktop MCPB bundle under `packaging/mcpb`
- `swag serve-mcp` asks for write and shell approval with MCP elicitation. Clients that cannot show the form get a denial in the tool result, or a preapproved grant from `swag setup --grant`. The server does not read stdin or write prompts to stdout
- MCP tools `swag_start_task`, `swag_task_status`, `swag_task_result`, and `swag_setup_status`
- Run bundles. `swag run --record` writes a portable, redacted bundle (plan, model traffic, tool results, approvals, file diffs, evidence ledger, undo tree hashes, plan fallback, strict plan, and memory mode). `swag replay` re-executes it from the saved model responses, or live to compare. `swag bundle inspect` and `swag bundle export` share a run. Format: `docs/spec/run-bundle.md`.
- Verification-gated skill learning. A successful run can be distilled into a Cowork-compatible `SKILL.md` and kept in `$SWAG_HOME/skill-candidates/` until evidence verification and a replay both pass. `swag skill learn|candidates|promote|reject|recheck`. Promoted skills land in `$SWAG_HOME/skills/` with provenance. Unverified runs are never activated.

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
