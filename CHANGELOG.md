# Changelog

All notable changes to Swag Bot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- One command to install and run a task: `scripts/install.sh` (and `scripts/install.ps1`), plus `uvx` / pipx instructions that install from Git until `PYPI_PUBLISHED` is flipped
- `swag setup --auto` detects a bring-your-own-key environment variable or a local Ollama model. It asks before pulling `qwen2.5:7b` (about 4.7 GB). A 3B-only install is not treated as ready
- `swag doctor --json` prints a readiness report with `ready` and does not include secret values
- `swag install-mcp` prints the Claude Code command, the Cursor and VS Code install links, and the Gemini, Claude Desktop, and ChatGPT notes
- Claude marketplace entry, Gemini CLI extension manifest, and a Claude Desktop MCPB bundle under `packaging/mcpb`
- `swag serve-mcp` asks for write and shell approval with MCP elicitation. Clients that cannot show the form get a denial in the tool result, or a preapproved grant from `swag setup --grant`. The server does not read stdin or write prompts to stdout
- MCP tools `swag_start_task`, `swag_task_status`, `swag_task_result`, and `swag_setup_status`

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
