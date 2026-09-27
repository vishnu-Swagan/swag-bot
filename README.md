# Swag Bot

Swag Bot is a free, MIT-licensed AI agent for complex multi-step tasks. It
plans a goal, carries the steps out, and checks its own work. Plugins use the
Claude Cowork / Claude Code layout (`.claude-plugin/plugin.json`, Agent
Skills, slash commands). The agent talks to MCP servers, and you can also
expose Swag Bot itself as one.

Bring your own model key, or run a local model through Ollama. Ollama is the
default, and it does not need an API key.

## Features

- Plan, do, and verify loop (`swag run`), with parallel independent steps
- Local sandbox by default, optional Docker sandbox
- Permission policy with autonomy levels `ask-always`, `ask-risky`, and `auto`
- Append-only action log with secret redaction
- Claude Cowork-compatible plugins, Agent Skills, slash commands, and a marketplace installer
- MCP client (stdio and streamable HTTP) and `swag serve-mcp`
- Ollama by default; OpenAI, Anthropic, Gemini, and OpenRouter through LiteLLM
- Pluggable memory: SQLite (default), a JSON file, or an external agentmemory server

## Install

Python 3.11 or newer. The package version for this release is 0.1.0.

From Git, with pip (this tracks the default branch):

```bash
python -m pip install "swag-bot @ git+https://github.com/vishnu-Swagan/swag-bot.git"
```

After the `v0.1.0` tag is pushed, pin that release:

```bash
python -m pip install "swag-bot @ git+https://github.com/vishnu-Swagan/swag-bot.git@v0.1.0"
```

With pipx, so the `swag` command is isolated from the rest of your Python:

```bash
pipx install "swag-bot @ git+https://github.com/vishnu-Swagan/swag-bot.git"
```

PyPI publishing is opt-in. A `v*` tag builds the package and creates a GitHub
Release either way. The workflow uploads to PyPI only when the repository
variable `PUBLISH_PYPI` is `true` and the `PYPI_API_TOKEN` secret is set.
Until then, install from Git. Once publishing is on, `python -m pip install swag-bot`
installs the same release.

Optional extras (add `@v0.1.0` to the URL to pin the release):

```bash
python -m pip install "swag-bot[models] @ git+https://github.com/vishnu-Swagan/swag-bot.git"
python -m pip install "swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot.git"
python -m pip install "swag-bot[sandbox] @ git+https://github.com/vishnu-Swagan/swag-bot.git"
```

`models` installs LiteLLM. `mcp` installs the official MCP SDK. `sandbox`
installs the Docker SDK, used when the `docker` CLI is not on `PATH`. A
checkout for development is `python -m pip install -e ".[dev]"`.

Swag Bot does not read a `.env` file. Export keys yourself. `.env.example`
lists the names. `swag doctor` prints `set` or `unset` and never the value.

## Quickstart with Ollama

Install [Ollama](https://ollama.com/), then pull a model:

```bash
ollama pull llama3.2
swag doctor
swag run "Summarize the files in this directory"
```

The default config is provider `ollama` and model `llama3.2`. The client
talks to `http://127.0.0.1:11434` unless `OLLAMA_HOST` or `model.api_base`
says otherwise. No API key is sent.

To pin that in `$SWAG_HOME/config.toml` (default directory `~/.swag`):

```bash
swag model set ollama/llama3.2
```

## Quickstart with a bring-your-own-key provider

```bash
python -m pip install "swag-bot[models] @ git+https://github.com/vishnu-Swagan/swag-bot.git"
export OPENAI_API_KEY=your-openai-key-here
swag model set openai/gpt-4o-mini
swag run "Draft a release checklist"
```

The same pattern works for `anthropic`, `gemini`, and `openrouter`. Keys are
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, and `OPENROUTER_API_KEY`. They stay in
the environment. They are not written to config.

```bash
swag model set openrouter/anthropic/claude-3.5-sonnet
```

## `swag run`

```bash
swag run "Write a short status note" --autonomy auto --output-dir ./swag-output/demo
```

`swag run` loads the configured model, the sandbox, and the permission
policy. It recalls matching memories, selects plugin skills whose
descriptions match the goal, and adds those instructions to the planner.
Built-in tools are `read_file`, `write_file`, and `run_shell`. MCP tools from
`~/.swag/mcp.json` and from enabled plugins are added when those servers
answer. After the run, a summary is saved to memory.

The output directory receives:

- `plan.json`
- `action-log.jsonl`
- `summary.md`

Other useful flags: `--dry-run`, `--max-steps`, `--max-attempts`,
`--concurrency`, `--model`, and `--engine` (`python` or `graphbit`).
GraphBit is optional (`pip install -e ".[graphbit]"`). The default scheduler
is pure Python. If GraphBit is not installed, `--engine graphbit` falls back
and says so.

`swag doctor` prints the config that would be used. A missing config file is
fine: the defaults above apply.

## Plugins

A plugin is a directory with `.claude-plugin/plugin.json`, `skills/*/SKILL.md`,
`commands/*.md`, `agents/*.md`, and an optional `.mcp.json`. The same tree
loads in Claude Cowork and Claude Code. Swag Bot's extra field is
`permissions`. Claude Code ignores unknown fields, so the file still loads
there.

```bash
swag plugin validate ./plugins/example-github-helper
swag plugin install ./plugins/example-github-helper
swag plugin list
swag skill list
```

`swag plugin install` prints the requested permissions and asks before it
copies anything. `--yes` prints the same list and skips the question.
Installed plugins live in `$SWAG_HOME/plugins/`. You can also point
`plugin_dirs` in `config.toml` at a checkout you are editing.

Authoring, marketplaces, and the skill format are in
[docs/PLUGINS.md](docs/PLUGINS.md).

Approving an install, or passing `--yes`, writes the requested permissions
into `$SWAG_HOME/grants.json`. Actions tagged with that plugin are allowed
when they need one of those permissions. Anything else stays denied.
Declining the prompt writes no grants. `swag plugin disable` suspends them
until `enable`, and `swag plugin remove` revokes them.

```bash
swag safety grant example-github-helper filesystem.write
```

## Permissions and autonomy

| Autonomy | When it prompts |
| --- | --- |
| `ask-always` | Every action, including reads |
| `ask-risky` (default) | Anything that is not a pure read |
| `auto` | Never. Actions are still logged. A hard deny still applies |

```bash
swag run "Rename the draft" --autonomy ask-risky
swag safety policy
swag safety log
```

The sandbox defaults to `local`: commands run in the task directory with a
timeout, and file paths cannot escape it. `sandbox.mode` can be `off`,
`local`, or `docker`. Docker runs a throwaway container with the network off
unless you turn it on. Details are in [docs/SAFETY.md](docs/SAFETY.md).

## MCP

Configure a server in `~/.swag/mcp.json` (the Claude Code `.mcp.json` shape):

```bash
swag mcp add local --command python --arg server.py
swag mcp add remote --url https://example.com/mcp --transport http --header "Authorization=Bearer ${API_TOKEN}"
swag mcp list
swag mcp tools
```

`${VAR}` placeholders are expanded when a client connects, not when the file
is saved. `swag mcp list` does not print env or header values.

`swag serve-mcp` exposes Swag Bot as an MCP server. Stdio is the default.
`--http` serves streamable HTTP on `127.0.0.1:8765`.

```bash
swag serve-mcp
swag serve-mcp --http --port 8765
```

The server offers `swag_run_task` (run a goal, return the summary) and
`swag_list_skills` (name and description of discovered skills). Install the
MCP extra first: `pip install "swag-bot[mcp]"`.

## Chrome

The side panel in `extension/` sends a task to Swag Bot on the same computer,
streams the plan, and asks you to approve or deny actions. It can attach the
current page, and, if you allow it, act in that tab. Chrome native messaging
is the bridge. There is no listening port and no remote server.

```bash
cd extension && npm install && npm run build
swag extension install
```

Quit Chrome completely, load `extension/dist` (or the Chrome Web Store build),
and click the Swag Bot icon. After a store install, add the published id with
`swag extension install --extension-id <id>`. Details are in
[extension/README.md](extension/README.md).

## Roadmap

- A browser-use plugin
- Telegram and Slack front ends
- A desktop app
- A plugin gallery

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT. Copyright 2026 Vishnu M / vishnu-Swagan. See [LICENSE](LICENSE).
