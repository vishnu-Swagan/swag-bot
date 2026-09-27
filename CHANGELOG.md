# Changelog

All notable changes to Swag Bot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Run bundles. `swag run --record` writes a portable, redacted bundle (plan, model traffic, tool results, approvals, file diffs, evidence ledger). `swag replay` re-executes it from the saved model responses, or live to compare. `swag bundle inspect` and `swag bundle export` share a run. Format: `docs/spec/run-bundle.md`.

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
