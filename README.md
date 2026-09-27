# Swag Bot

Free, public, open-source AI agent that completes complex multi-step tasks.
MIT licensed.

Swag Bot plans a task, carries the steps out, and checks its own work. Plugins
use the Claude Cowork / Claude Code layout (`.claude-plugin/plugin.json`,
Agent Skills, slash commands), and the agent can talk to MCP servers. You
bring your own model key, or you run a local model through Ollama.

## Status

Early development. This repository is the package skeleton and the shared
contracts. The plan-do-verify loop, the plugin loader, the sandbox, and the
model clients are stubs. Ownership and the rules for working in parallel are
in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quickstart

Python 3.11 or newer.

```bash
python -m pip install -e ".[dev]"
swag doctor
swag --help
```

`swag doctor` prints the config it would use (`~/.swag/config.toml`, or
`$SWAG_HOME/config.toml`) and whether optional pieces such as LiteLLM, the
MCP SDK, and Docker are installed. A missing config file is fine: built-in
defaults are used. API keys stay in the environment. See `.env.example` for
the variable names. Swag Bot does not read a `.env` file on its own, and it
never prints a key.

`swag version` prints the package version. `swag run` is the entry point for
a task and is not implemented yet.

## License

MIT. Copyright 2026 Vishnu M / vishnu-Swagan. See [LICENSE](LICENSE).
