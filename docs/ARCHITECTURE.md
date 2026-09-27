# Architecture

Swag Bot is a free, MIT-licensed agent. This repository is the foundation:
the package layout, the CLI, and the shared contracts. Four agents implement
the real behavior in parallel, each on a branch that starts from this one.
They do not edit each other's folders.

v0 wires the four areas together. `swag run` uses the configured model
(Ollama by default), the safety sandbox and permission policy, built-in tools
plus MCP servers from config and enabled plugins, skills selected for the
goal, and memory (recall before planning, save a summary after).
`swag serve-mcp` runs a real task and lists discovered skills.

## Module map

```
src/swag_bot/
  cli.py            root Typer app (swag version, swag doctor, registers sub-apps)
  config.py         ~/.swag/config.toml, override with SWAG_HOME
  errors.py         SwagError, ConfigError, SandboxError, NotImplementedYet
  interfaces.py     protocols and pydantic models (the contract)
  registry.py       InMemoryToolRegistry, the default ToolRegistry
  core/             plan-do-verify loop, swag run
  plugins/          Cowork-compatible plugins, Agent Skills, slash commands
  safety/           sandbox, permissions, action log
  mcp/              MCP client and swag serve-mcp
  models/           LiteLLM / Ollama / bring-your-own-key clients
  memory/           pluggable MemoryStore
tests/fakes.py      FakeLLMClient, FakeSandbox, InMemoryMemoryStore, AutoApprovePrompter
```

Import direction:

```
cli.py  ->  config, errors, each package's cli.py
config  ->  interfaces, errors
owned packages  ->  interfaces, config, errors
interfaces  ->  errors
errors  ->  stdlib only
```

Owned packages do not import each other. The core loop takes an `LLMClient`,
a `Sandbox`, a `MemoryStore`, a `PermissionPolicy`, and an `ApprovalPrompter`
in its constructor. `swag run` (owned by the core agent) is the composition
root and may call the public factories:

| Factory | Module |
| --- | --- |
| `build_llm_client(settings)` | `swag_bot.models` |
| `build_memory_store(settings)` | `swag_bot.memory` |
| `build_sandbox(settings)` | `swag_bot.safety` |
| `build_permission_policy(settings)` | `swag_bot.safety` |
| `build_prompter(settings)` | `swag_bot.safety` |
| `build_mcp_client(settings)` | `swag_bot.mcp` |
| `discover_plugins(settings)` / `load_plugin(root)` | `swag_bot.plugins` |

The root `swag` command is the other composition point. It injects the MCP
task runner and the grant store that `swag plugin install` uses to write
`$SWAG_HOME/grants.json`. The plugins package does not import safety.

`swag run` calls these factories. If one still raises `NotImplementedYet`,
the command uses a small in-process stand-in, except for the model client.
Unit tests inject objects from `tests/fakes.py` and do not need the factories.

## Ownership

| Agent | May edit | CLI |
| --- | --- | --- |
| Core | `src/swag_bot/core/`, `tests/core/` | `swag run` |
| Plugins | `src/swag_bot/plugins/`, `tests/plugins/` | `swag plugin ...` |
| Safety and MCP | `src/swag_bot/safety/`, `src/swag_bot/mcp/`, `tests/safety/`, `tests/mcp/` | `swag safety`, `swag mcp`, `swag serve-mcp` |
| Models and memory | `src/swag_bot/models/`, `src/swag_bot/memory/`, `tests/models/`, `tests/memory/` | `swag model`, `swag memory` |

Each package has a `README.md` with the same boundary and a description of
what to build. Each `cli.py` is a Typer app the root app already registers.
Add commands there. Do not rename the group.

The safety/mcp agent may edit the `serve-mcp` function in `src/swag_bot/cli.py`
when the parameters of `swag_bot.mcp.cli.serve` change. That wrapper only
forwards `host` and `port`. No other edits to the root CLI.

Shared files (`interfaces.py`, `config.py`, `errors.py`, `registry.py`,
`tests/fakes.py`, the top-level `tests/test_*.py` files, `pyproject.toml`)
are not owned by one agent. Rules for changing them are below.

## Contracts

`src/swag_bot/interfaces.py` is the vocabulary. Data is a pydantic model.
Behavior is a `typing.Protocol` marked `@runtime_checkable`.

### Models

`LLMClient.chat` takes `Sequence[Message]` and optional tools and returns a
`ChatResponse`. `LLMClient.complete` is a single prompt in, string out.
Streaming is a separate `StreamingLLMClient`. Do not implement it by
buffering and pretending. Tool arguments are a dict. `ToolCall` accepts a
JSON string from a provider and parses it.

`Message` roles are `system`, `user`, `assistant`, and `tool`. Tool results
use `Message.tool(tool_call_id, content)`.

`ToolRegistry` registers a `Tool` plus a callable. `call` returns text for
the next tool message. `InMemoryToolRegistry` is the default. The method is
`list_tools`, not `list`.

### Skills and plugins

Agent Skills (https://agentskills.io/specification) load in three steps:

1. `SkillMeta` is `name` and `description` (plus optional license,
   compatibility, metadata, and `allowed-tools`). This is all that is loaded
   at startup.
2. `Skill.instructions()` is the `SKILL.md` body.
3. `Skill.resources()` lists files; `Skill.read_resource()` reads one.

`name` is 1-64 characters, lowercase letters, digits, and single hyphens.
The skill directory name must match `name`. The loader checks that.
`description` is 1-1024 characters. This package does not depend on a YAML
library; the plugins agent parses frontmatter and calls
`SkillMeta.model_validate`.

`PluginManifest` mirrors `.claude-plugin/plugin.json`: `name`, `displayName`,
`version`, `description`, `author`, `homepage`, `repository`, `license`,
`keywords`, `defaultEnabled`, `skills`, `commands`, `agents`, `workflows`,
`hooks`, `mcpServers`, `outputStyles`, `lspServers`, `userConfig`, `channels`,
`experimental`, `dependencies`. Unknown keys are kept (`extra="allow"`),
which is the same rule Claude Code uses.

`permissions` is a Swag Bot extension on that file. Claude Code ignores
unknown fields, so the same `plugin.json` still loads there. Built-in names
are `Permission`: `filesystem.read`, `filesystem.write`, `shell`, `network`,
`mcp`, `secrets`. Other dotted names are allowed. Unknown names are risky.

`Plugin` exposes the manifest, the root path, `list_skills()` (metadata
only), `load_skill(name)`, and `list_commands()` of `SlashCommand`. Command
bodies stay empty until the command is invoked.

### Safety

`AutonomyLevel`: `ask-always`, `ask-risky`, `ask-irreversible`, `auto`.
`ask-irreversible` prompts only for `Reversibility.IRREVERSIBLE`. The default
stays `ask-risky`. `UndoController` is the optional snapshot hook the loop
calls around a run; `swag undo` restores those snapshots.

`RiskLevel`: `read`, `write`, `execute`, `network`, `destructive`.

`default_requires_approval(autonomy, risk)` is the rule. `ask-always` prompts
for everything. `ask-risky` prompts unless the risk is `read`. `auto` does
not prompt. A policy may deny more often, including a hard deny. It must not
prompt less often than the helper.

`PermissionPolicy` exposes `autonomy`, `classify`, and `requires_approval`.
`classify` must not lower a `destructive` risk. `ApprovalPrompter.prompt`
returns True to allow.

`Sandbox` has `workdir`, `run(command, timeout=...)`, `read_file`, and
`write_file`. Paths go through `resolve_sandbox_path`, which rejects absolute
paths, `..`, and symlinks that leave the workdir. Files are UTF-8 text.
`command` is a shell string; the safety agent decides how it runs. On
timeout, return a `CommandResult` with `timed_out=True` and `exit_code` 124
(`TIMEOUT_EXIT_CODE`). Do not raise for a timeout.

`ActionLogEntry` is append-only. `approver` is `policy` (no prompt), `user`
(a prompter answered), or `auto`. Redact secrets before building an
`ActionRequest`. The log stores that object.

### Memory and the plan

`MemoryStore`: `add`, `search`, `get`, `delete`. `search` is best-first.
An empty query returns nothing. `get` returns None when the id is missing.
`delete` returns True only if the item existed. The default backend name is
`memory` and it does not use the network. `InMemoryMemoryStore` in
`tests/fakes.py` is the behavior to match: case-insensitive substring over
content and metadata values, newest match first.

`TaskPlan` holds `Step`s. Status values: `pending`, `doing`, `verifying`,
`done`, `failed`, `skipped`. `done` means the step ran and the check passed.
Step ids are unique, and `depends_on` may only name steps in the same plan.
`StepResult` is the outcome of one step. `AgentLoop.run(goal)` returns the
plan. `PlanDoVerifyLoop` in `core/loop.py` is the implementation. `swag run`
passes recalled memories and selected skill instructions in as planner context.

### MCP

`MCPServerSpec` is one entry from a plugin `mcpServers` map. `MCPClient`
lists tools as shared `Tool` values, calls one by name, and returns text.
`close` is safe to call twice. The core loop should not special-case MCP.

## Config

`load_settings()` reads `$SWAG_HOME/config.toml`, or `~/.swag/config.toml`.
A missing file returns defaults. A broken file raises `ConfigError`.

Defaults: provider `ollama`, model `llama3.2`, autonomy `ask-risky`,
memory backend `memory`, sandbox mode `local`, image `python:3.12-slim`,
sandbox network off, plugin dirs empty.

Keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`OPENROUTER_API_KEY`) are environment variables. They are not config fields.
`swag doctor` prints `set` or `unset` and never the value. Swag Bot does not
load `.env` by itself.

`sandbox.mode` is `off`, `local`, or `docker`.

## CLI

| Command | Status |
| --- | --- |
| `swag run "<goal>"` | plans, runs, and verifies; writes `summary.md` |
| `swag plugin` / `swag skill` | load, install, and list Cowork-compatible plugins and skills |
| `swag safety log\|policy` | action log and autonomy rules |
| `swag mcp list\|tools\|add\|remove` | MCP servers in `~/.swag/mcp.json` |
| `swag serve-mcp` | stdio MCP server; `--http` for streamable HTTP. Runs tasks and lists skills |
| `swag model list\|test\|set` | Ollama by default, LiteLLM for bring-your-own-key providers |
| `swag memory add\|search\|list\|forget` | SQLite by default |
| `swag version` | prints `swag-bot` and the version |
| `swag doctor` | prints config and optional-dep status |

Optional extras, not installed by CI: `.[models]` (litellm), `.[mcp]` (mcp),
`.[sandbox]` (docker). `.[dev]` is pytest, ruff, and mypy.

## Rules for the parallel agents

1. Branch from this foundation branch. Do not branch from another agent's
   work, and do not push commits onto the foundation branch.
2. Edit only your folders from the ownership table, plus tests under
   `tests/<area>/`. Create that test directory; it is not in the tree yet.
3. Changes to `interfaces.py` are additive only. New fields need defaults.
   New protocols, enum members, and functions are fine. Do not rename, do
   not remove, and do not tighten a type so that existing values stop
   validating. Adding an enum member is fine. Changing an enum value is not.
4. `config.py`: new settings need defaults. Do not rename existing keys.
   Do not store secrets there.
5. `tests/fakes.py`: you may extend a fake. Do not change the success path
   of the methods listed at the top of that file.
6. Keep the top-level smoke tests green (`tests/test_*.py`).
7. No AGPL code in core. The project is MIT. Do not copy AGPL, SSPL, or
   other network-copyleft source into any package, and do not add those
   licenses as dependencies. Core in particular stays MIT-only.
8. No real secrets in the repo, in tests, in fixtures, or in docs. Placeholders
   belong in `.env.example` only. `.env` is gitignored.
9. Do not add a heavy library to the base `dependencies` list. Put provider
   SDKs in an optional extra. The base install stays typer, pydantic,
   tomli-w, and rich.
10. Prefer injecting protocols over importing another owned package. The
    one intended cross-call is the factories above, from `swag run`.

## Tests

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy
pytest
swag --help
```

CI runs ruff, mypy, and pytest on Python 3.11 and 3.12. mypy is `strict` on
the `swag_bot` package.
