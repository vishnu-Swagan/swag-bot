# Install Swag Bot from one prompt

Paste the block below into Claude, Cursor, VS Code, Gemini, or another
coding agent. It is the whole install. Do not add API keys to the prompt.

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

Claude Code:
  claude mcp add --transport stdio swag -- uvx --from 'swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot' swag-bot serve-mcp

Claude Code or Cowork plugin:
  claude plugin marketplace add vishnu-Swagan/swag-bot
  claude plugin install swag-bot@swag-bot

Cursor (open this link, then approve the install):
  cursor://anysphere.cursor-deeplink/mcp/install?name=swag&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJzd2FnLWJvdFttY3BdIEAgZ2l0K2h0dHBzOi8vZ2l0aHViLmNvbS92aXNobnUtU3dhZ2FuL3N3YWctYm90Iiwic3dhZy1ib3QiLCJzZXJ2ZS1tY3AiXX0%3D

VS Code:
  vscode:mcp/install?%7B%22name%22%3A%22swag%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22swag-bot%5Bmcp%5D%20%40%20git%2Bhttps%3A%2F%2Fgithub.com%2Fvishnu-Swagan%2Fswag-bot%22%2C%22swag-bot%22%2C%22serve-mcp%22%5D%7D

Gemini CLI:
  gemini extensions install https://github.com/vishnu-Swagan/swag-bot

Claude Desktop: pack packaging/mcpb with
  npx @anthropic-ai/mcpb pack packaging/mcpb swag-bot.mcpb
and open the .mcpb file. Sign a release build with
  npx @anthropic-ai/mcpb sign swag-bot.mcpb

ChatGPT cannot attach a local stdio MCP server. `swag serve-mcp --http`
listens on 127.0.0.1 only. There is no hosted relay.

After the server is connected, call swag_setup_status. If ready is false,
stop and tell me why. Otherwise call swag_run_task, or swag_start_task plus
swag_task_status for a long run. If the result says an action was denied,
show me that text. Do not look for a yes/no prompt on the server's stdin.
```

## What the commands are checked against

Checked on 2026-09-27:

- Claude Code MCP: `claude mcp add --transport stdio <name> -- <command>`
  from https://code.claude.com/docs/en/mcp
- Claude marketplace: https://code.claude.com/docs/en/plugin-marketplaces
  (`claude plugin marketplace add owner/repo`, then
  `claude plugin install name@marketplace`). Cowork uses the same files.
- Cursor install links: https://cursor.com/docs/mcp/install-links
  (`config` is base64 of the server object only)
- VS Code: https://code.visualstudio.com/api/extension-guides/ai/mcp
  (`vscode:mcp/install?` plus URL-encoded JSON)
- Gemini CLI extensions: https://geminicli.com/docs/extensions/reference
- Claude Desktop MCPB, manifest 0.4, server type `uv`:
  https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md
  Pack and sign with `npx @anthropic-ai/mcpb`.

`swag install-mcp` prints the same commands from the code that the tests lock
to these files.

## Approvals over MCP

`swag serve-mcp` speaks MCP on stdin and stdout. It does not ask `Allow this
action?` there. A client that declares form elicitation gets one question
per task. A client that does not is told, in the tool result, that the
action was denied. Preapprove a risk in a terminal with
`swag setup --grant write` (also `read`, `execute`, `network`, or
`destructive`). A task-level yes does not cover destructive actions.

## Switching to PyPI

When https://pypi.org/project/swag-bot/ exists, set `PYPI_PUBLISHED = True`
in `src/swag_bot/onboarding/distribution.py`, set `PYPI_PUBLISHED=1` in
`scripts/install.sh`, and set `$PypiPublished = 1` in `scripts/install.ps1`.
Generated commands then use the package name with no Git URL. Until that
flag changes, the Git URL above is the install that works.
