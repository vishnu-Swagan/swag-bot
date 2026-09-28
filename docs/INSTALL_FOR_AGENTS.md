# Install Swag Bot from one prompt

Paste one block below into the client you are using. Each block is the whole
install for that client. Do not fill in placeholders, and do not add API keys.

A local model often needs more than two minutes. After Swag Bot is connected,
prefer `swag_start_task`, then poll `swag_task_status` until it is not
`running`, and read `swag_task_result`. Claude Code moves an MCP call to the
background after 120 seconds (`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS`, default
120000). That second turn can call the same local Ollama server while the
first call is still running, and the run times out. For a local model, either
poll with `swag_start_task` or start Claude Code with
`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`.

## Claude Code

```text
Connect Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) to this chat.
Use the Bash tool to run this one command:

uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot setup --auto && claude plugin marketplace add vishnu-Swagan/swag-bot && claude plugin install swag-bot@swag-bot

It picks a local model, then installs the Swag Bot plugin (its MCP server).
Do not install anything else. When it finishes, tell me to type /reload-plugins --force.
```

`claude mcp add` is a different path. It does not load inside the current
session: exit Claude Code and start it again. The command is
`claude mcp add --transport stdio swag -- uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot serve-mcp`.

## Cursor

```text
Connect Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) to this chat.
Use the shell to run this one command:

uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot setup --auto

Then open this link and approve the install:
cursor://anysphere.cursor-deeplink/mcp/install?name=swag&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJzd2FnLWJvdFttY3BdIEAgZ2l0K2h0dHBzOi8vZ2l0aHViLmNvbS92aXNobnUtU3dhZ2FuL3N3YWctYm90Iiwic3dhZy1ib3QiLCJzZXJ2ZS1tY3AiXX0%3D

Do not install anything else. After you approve it, restart Cursor so the swag tools load.
```

## Codex

```text
Connect Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) to this chat.
Use the shell to run this one command:

uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot setup --auto && codex mcp add swag -- uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot serve-mcp

Do not install anything else. Quit Codex and start it again so the swag tools load.
```

## Gemini CLI

```text
Connect Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) to this chat.
Use the shell to run this one command:

uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot setup --auto && gemini extensions install https://github.com/vishnu-Swagan/swag-bot

Do not install anything else. Quit Gemini CLI and start it again so the extension loads.
```

## Claude Desktop

```text
Connect Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) to Claude Desktop.
From a checkout of that repo, run:

npx @anthropic-ai/mcpb pack packaging/mcpb swag-bot.mcpb

Open swag-bot.mcpb in Claude Desktop and approve the extension.
Do not install anything else. Quit Claude Desktop and open it again so the swag tools load.
```

## VS Code / Copilot

```text
Connect Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) to this chat.
Use the terminal to run this one command:

uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot setup --auto

Then open this link and approve the install:
vscode:mcp/install?%7B%22name%22%3A%22swag%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22swag-bot%5Bmcp%5D%20%40%20git%2Bhttps%3A%2F%2Fgithub.com%2Fvishnu-Swagan%2Fswag-bot%22%2C%22swag-bot%22%2C%22serve-mcp%22%5D%7D

Do not install anything else. Run Developer: Reload Window so the swag tools load.
```

## Generic MCP

```text
Connect Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) to this chat.
Use the shell to run:

uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot setup --auto

Add this stdio server to the client's MCP config, under the name swag:

{"command":"uvx","args":["--from","swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot","swag-bot","serve-mcp"]}

Do not install anything else. Restart the client so the swag tools load.
```

For a long task, call `swag_start_task`, then `swag_task_status`, then
`swag_task_result`. Do not leave a single `swag_run_task` running against a
local model for more than a minute unless
`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` is set.

## Reference prompt

The block below is the long form. It still contains the words `THE TASK` on
purpose, as a placeholder for a human who already has a goal. Prefer a short
prompt above when the client is a small model.

```text
Install Swag Bot (MIT, https://github.com/vishnu-Swagan/swag-bot) and use it
for the task I just described.

Terminal, from a checkout of that repo:
  sh scripts/install.sh -- run "THE TASK"
That script asks before it installs uv, then runs `swag setup --auto`, which
asks before it downloads a model. Do not pass --yes unless I already agreed.
Do not install Ollama, Docker, or anything else unless I say so.

No checkout, one shot:
  uvx --from 'swag-bot[models] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot run "THE TASK"

Or:
  pipx install "swag-bot[mcp,models] @ git+https://github.com/vishnu-Swagan/swag-bot"
  swag setup --auto
  swag run "THE TASK"

Setup uses ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or
OPENROUTER_API_KEY when one is already exported. It never writes the key
into config. Gemini's client reads GEMINI_API_KEY, not GOOGLE_API_KEY.
It also uses an Ollama model of at least 7B, or a running local
OpenAI-compatible server (LM Studio, Jan, llama.cpp, llamafile, GPT4All).
If no key is set and Ollama is running without a 7B-class model, setup
offers to pull qwen2.5:7b (about 4.7 GB). A 3B model is not good enough.
If nothing local is available, it offers a free cloud plan. Those plans
send prompts to the provider. Read docs/MODELS.md before picking one.
If Ollama is missing, send me to https://ollama.com/download.

Check readiness with `swag doctor --json`. Use the result only when "ready"
is true. The JSON does not contain secrets.

To call Swag Bot from this chat, add its MCP server. Do not point the
server at a secret.

Claude Code plugin (then type /reload-plugins --force in this session):
  claude plugin marketplace add vishnu-Swagan/swag-bot
  claude plugin install swag-bot@swag-bot

Claude Code MCP (exit Claude Code and start it again; this session will not
see a server added with claude mcp add):
  claude mcp add --transport stdio swag -- uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot serve-mcp

Cursor (open this link, approve the install, then restart Cursor):
  cursor://anysphere.cursor-deeplink/mcp/install?name=swag&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJzd2FnLWJvdFttY3BdIEAgZ2l0K2h0dHBzOi8vZ2l0aHViLmNvbS92aXNobnUtU3dhZ2FuL3N3YWctYm90Iiwic3dhZy1ib3QiLCJzZXJ2ZS1tY3AiXX0%3D

VS Code / Copilot (open the link, then run Developer: Reload Window):
  vscode:mcp/install?%7B%22name%22%3A%22swag%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22swag-bot%5Bmcp%5D%20%40%20git%2Bhttps%3A%2F%2Fgithub.com%2Fvishnu-Swagan%2Fswag-bot%22%2C%22swag-bot%22%2C%22serve-mcp%22%5D%7D

Codex (then quit Codex and start it again):
  codex mcp add swag -- uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot serve-mcp

Gemini CLI (then quit Gemini CLI and start it again):
  gemini extensions install https://github.com/vishnu-Swagan/swag-bot

Claude Desktop: pack packaging/mcpb with
  npx @anthropic-ai/mcpb pack packaging/mcpb swag-bot.mcpb
and open the .mcpb file. Quit Claude Desktop and open it again. Sign a
release build with
  npx @anthropic-ai/mcpb sign swag-bot.mcpb

ChatGPT cannot attach a local stdio MCP server. `swag serve-mcp --http`
listens on 127.0.0.1 only. There is no hosted relay.

After the server is connected, call swag_setup_status. If ready is false,
stop and tell me why, including the fix command in reason. Otherwise, for a
short task, call swag_run_task. For anything that may take more than a
minute, call swag_start_task and poll swag_task_status, then read
swag_task_result. On Claude Code with a local model, set
CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0 or the client will background the call
at 120 seconds and hit the same Ollama server twice. If the result says an
action was denied, or that the user declined, show me that text. Do not
invent file contents; use the files listed in the tool result. Do not look
for a yes/no prompt on the server's stdin.
```

## What the commands are checked against

Checked on 2026-09-28:

- Claude Code MCP: `claude mcp add --transport stdio <name> -- <command>`
  from https://code.claude.com/docs/en/mcp. Claude Code reads MCP config at
  session start, so exit and start Claude Code again after `claude mcp add`.
- Claude marketplace: https://code.claude.com/docs/en/plugin-marketplaces
  (`claude plugin marketplace add owner/repo`, then
  `claude plugin install name@marketplace`). A plugin that ships an MCP
  server needs `/reload-plugins --force` in the current session (a plain
  `/reload-plugins` can skip the MCP server). Cowork uses the same files.
- Claude Code backgrounds an MCP tool call after
  `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` milliseconds (default 120000). `0`
  turns that off. https://code.claude.com/docs/en/env-vars
- Cursor install links: https://cursor.com/docs/mcp/install-links
  (`config` is base64 of the server object only). Restart Cursor after
  approving the link.
- VS Code: https://code.visualstudio.com/api/extension-guides/ai/mcp
  (`vscode:mcp/install?` plus URL-encoded JSON). Reload the window after
  approving the link. Copilot uses the same MCP config.
- Codex CLI: `codex mcp add <name> -- <command>`. Restart Codex after it.
- Gemini CLI extensions: https://geminicli.com/docs/extensions/reference.
  Restart Gemini CLI after `gemini extensions install`.
- Claude Desktop MCPB, manifest 0.4, server type `uv`:
  https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md
  Pack and sign with `npx @anthropic-ai/mcpb`. Quit and reopen Claude Desktop
  after opening the `.mcpb` file.

`swag install-mcp` prints the same commands from the code that the tests lock
to these files.

## Approvals over MCP

`swag serve-mcp` speaks MCP on stdin and stdout. It does not ask `Allow this
action?` there. A client that declares form elicitation gets one question
per task. The form title is the action and target, such as
`Run: python3 fizzbuzz.py`. The goal text is in the form body. Declining or
cancelling that form stops the task. The run ends not met, `summary.md` says
the user declined, and the tool result has `isError` set. A client that does
not offer a form is told, in the tool result, that the action was denied.
Preapprove a risk in a terminal with `swag setup --grant write` (also
`read`, `execute`, `network`, or `destructive`). A task-level yes does not
cover destructive actions.

## Switching to PyPI

When https://pypi.org/project/swag-bot/ exists, set `PYPI_PUBLISHED = True`
in `src/swag_bot/onboarding/distribution.py`, set `PYPI_PUBLISHED=1` in
`scripts/install.sh`, and set `$PypiPublished = 1` in `scripts/install.ps1`.
Generated commands then use the package name with no Git URL. Until that
flag changes, the Git URL above is the install that works.
