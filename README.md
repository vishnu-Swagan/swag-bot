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

## One command

From a checkout, this installs uv after asking, installs Swag Bot, picks a
model, and runs the task. It asks again before downloading a model.

```bash
sh scripts/install.sh -- run "Summarize the files in this directory"
```

`--dry-run` prints the commands and changes nothing. `--yes` skips both
questions. The PowerShell twin is `scripts/install.ps1`.

Without cloning, uv can install from Git and run one task:

```bash
uvx --from 'swag-bot[models] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot run "Summarize the files in this directory"
```

pipx:

```bash
pipx install "swag-bot[mcp,models] @ git+https://github.com/vishnu-Swagan/swag-bot"
swag setup --auto
swag run "Summarize the files in this directory"
```

`swag setup --auto` uses an API key it finds in the environment
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or
`OPENROUTER_API_KEY`, and the free-plan names in
[docs/MODELS.md](docs/MODELS.md)), an Ollama model of at least 7B, or another
local OpenAI-compatible server that is already running (LM Studio, Jan,
llama.cpp, llamafile, GPT4All). Otherwise it offers to pull `qwen2.5:7b`
(about 4.7 GB) and waits for a yes, or, when nothing local is available,
prints a free-cloud menu. It does not install Ollama or those apps for you.
A 3B model is not selected when the size is visible in the model id.
Point at any other OpenAI-compatible server with
`swag setup --auto --base-url http://localhost:1234/v1`.
Local servers keep prompts on this machine. A free cloud plan does not: it
sends prompts to that provider and rate-limits them. The trade-off, the key
pages, and the default model ids are in [docs/MODELS.md](docs/MODELS.md).

The PyPI project is not published yet. Flip `PYPI_PUBLISHED` in
`src/swag_bot/onboarding/distribution.py` (and the same flag in the two
install scripts) after it is. The commands then become `uvx swag-bot run "..."`.

`swag doctor --json` prints `"ready": true` or false and never prints a key.

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

The server offers `swag_run_task` (run a goal, return the summary),
`swag_start_task` / `swag_task_status` / `swag_task_result` (the same run,
polled), `swag_list_skills`, and `swag_setup_status`. Install the MCP extra
first.

Write and shell actions are not confirmed on the terminal. Stdio is the MCP
channel, so a prompt there would break the session. A client that supports
form elicitation gets one question per task. Otherwise the action is denied
and the tool result says why, unless you preapproved it:

```bash
swag setup --grant write
```

Destructive actions stay denied until you grant that risk explicitly.
`ask-risky` is still the default.

Connect a client with one command or link (`swag install-mcp` prints these):

```bash
claude mcp add --transport stdio swag -- uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot serve-mcp
```

Claude Code and Cowork can also install the plugin from this repo:

```bash
claude plugin marketplace add vishnu-Swagan/swag-bot
claude plugin install swag-bot@swag-bot
```

- Cursor: `cursor://anysphere.cursor-deeplink/mcp/install?name=swag&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJzd2FnLWJvdFttY3BdIEAgZ2l0K2h0dHBzOi8vZ2l0aHViLmNvbS92aXNobnUtU3dhZ2FuL3N3YWctYm90Iiwic3dhZy1ib3QiLCJzZXJ2ZS1tY3AiXX0%3D`
- VS Code: `vscode:mcp/install?%7B%22name%22%3A%22swag%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22swag-bot%5Bmcp%5D%20%40%20git%2Bhttps%3A%2F%2Fgithub.com%2Fvishnu-Swagan%2Fswag-bot%22%2C%22swag-bot%22%2C%22serve-mcp%22%5D%7D`
- Gemini CLI: `gemini extensions install https://github.com/vishnu-Swagan/swag-bot`
- Claude Desktop: pack `packaging/mcpb` with `npx @anthropic-ai/mcpb pack packaging/mcpb swag-bot.mcpb` and open the `.mcpb` file
- ChatGPT cannot attach a local stdio server. There is no hosted relay in this repo

The paste-this prompt for an AI chat is [docs/INSTALL_FOR_AGENTS.md](docs/INSTALL_FOR_AGENTS.md). A short index is [llms.txt](llms.txt).

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
