# Safety and MCP

This is the safety and MCP slice of Swag Bot: where commands run, when the
agent asks, the append-only record of what it did, and how MCP servers are
connected. The core loop stays unaware of those details. It receives a
`Sandbox`, a `PermissionPolicy`, an `ApprovalPrompter`, and an `MCPClient`.

## Sandbox

`build_sandbox(settings)` reads `sandbox.mode` from config.

| Mode | Behavior |
| --- | --- |
| `local` | `LocalSandbox`. A subprocess with `cwd` set to the workdir, a timeout, and an environment that drops API keys and other secrets. |
| `docker` | `DockerSandbox` when the `docker` CLI is on `PATH`, or the Docker SDK (`pip install 'swag-bot[sandbox]'`) when the CLI is missing. Otherwise it falls back to `LocalSandbox` and prints a warning. |
| `off` | File reads and writes still stay in the workdir. `run` raises `SandboxError`. |

Every file path goes through `resolve_sandbox_path`. Absolute paths, `..`, and symlinks that leave the workdir are rejected.

Docker runs a throwaway container (`--rm`) with the workdir mounted at `/work`. Network is off unless `sandbox.network` is true. CPU, memory, and pid limits are set, capabilities are dropped, and the root filesystem is read-only aside from the workdir mount and a small `/tmp`. A timeout returns `CommandResult` with `timed_out=True` and exit code 124. It does not raise.

`LocalSandbox` is not a container. It is the fallback when Docker is missing.

## Permissions

`build_permission_policy(settings)` uses `settings.autonomy` and the active grants from `$SWAG_HOME/grants.json`.

Approving `swag plugin install`, or passing `--yes`, writes the plugin's requested permissions into that file. The root command injects a grant store; the plugins package does not import this one. A declined install writes no grants. `swag plugin disable` moves that plugin's grants to a `suspended` object, which `load_grants` does not apply, so tagged actions are denied until `swag plugin enable` moves them back. `swag plugin remove` deletes the plugin from both objects. `swag safety grant` and `swag safety revoke` edit whichever object currently holds the plugin, so a grant issued while the plugin is disabled does not turn the deny back into an allow.

| Autonomy | When it prompts |
| --- | --- |
| `ask-always` | Every action, including reads. |
| `ask-risky` | Anything that is not a pure read. This is the default. |
| `ask-irreversible` | Only irreversible actions: the point of no return. Reversible workspace edits and compensable actions are not prompted. |
| `auto` | Never. Actions are still logged. A hard deny still applies. |

Classification raises risk; it never lowers `destructive`.

| Action | Risk |
| --- | --- |
| Read inside the workdir | `read` |
| File write | `write` |
| Shell, and MCP tool calls | `execute` |
| Network, and sending messages | `network` |
| Delete, spending money, write outside the workdir | `destructive` |
| Unknown permission names | at least `write` (risky) |

`requires_approval` never prompts less often than `default_requires_approval`. `decide` can also return `deny` with no prompt when an action is tagged with `arguments["plugin"]` and that plugin does not hold the matching active grant (`filesystem.read`, `filesystem.write`, `shell`, `network`, `mcp`, `secrets`, or a custom dotted name). Install grants do not lower that deny for a permission the user did not approve, and they do not lower a `destructive` classification.

`build_prompter(settings)` is a rich terminal prompt. The default answer is no.

`authorize(...)` redacts secrets, asks the policy, maybe prompts, and appends a log line. `approver` is `policy`, `user`, or `auto`.

## Undo ledger

Before every file write and every shell command, Swag Bot stores a content-addressed snapshot of the sandbox workdir. The blobs are SHA-256 files under `$SWAG_HOME/undo`, outside the workdir, so a shell `rm` inside the task directory cannot delete the history that would restore it. Unchanged files are stored once and reused by hash. `git` is not required, and the project's own `.git` directory is just more files in the snapshot when it sits inside the workdir.

```bash
swag undo
swag undo --to edit-files
swag undo --run <run-id> --to edit-files
```

`swag undo` restores the workspace to the start of the most recent run, including files a shell command edited, created, or deleted. `--to` restores the workspace to the start of that step and undoes that step and every step that started after it. A failed step is rolled back the same way when `undo.auto_rollback` is true (the default). Set `undo.enabled = false` to turn snapshots off. Neither setting changes the default autonomy, which stays `ask-risky`.

`ask-irreversible` is a separate approval mode. It asks only when the action is irreversible. `ask-risky` still asks for ordinary writes and shell commands, and the approval panel marks an irreversible action as a point of no return.

External side effects are not in the snapshot. A plugin or MCP tool can declare an inverse:

```json
{
  "name": "issues",
  "compensations": [
    {
      "tool": "create_issue",
      "inverse": "close_issue",
      "description": "Close the issue this tool created.",
      "argument_map": {"number": "number"},
      "entrypoint": "my_plugin.compensate:close_issue"
    }
  ]
}
```

An MCP tool can put the same object in its metadata as `swagCompensation`. `argument_map` copies stored arguments onto the inverse (`"outcome"` uses the tool result). `entrypoint` is `module:function`. The function receives the resolved argument dict. Undo runs compensations in reverse order. A callable registered in the same process with `CompensationRegistry.register` runs too.

### Limits

These are real limits, not edge cases to ignore:

- The snapshot is the sandbox workdir only. A shell command can still change files outside that directory, talk to the network, send mail, spend money, or start another process. Those effects are classified irreversible (or compensable, when an inverse actually runs). Undo lists irreversible actions. It does not claim to have undone them.
- Shell classification is a heuristic. `curl`, `git push`, a redirect onto an absolute path, and `rm /somewhere` are treated as irreversible. A Python one-liner that opens an absolute path can be missed. Mixed commands (`echo hi > notes.txt` and `curl` in one line) are irreversible, and the workspace half is still restored because the snapshot was taken first.
- A compensation declared without a callable is reported as not run. Undo does not invent the inverse.
- `entrypoint` imports and runs plugin code at undo time. That is the same trust as installing the plugin.
- Sockets, devices, and fifos are not restored. Symlinks are restored as links and are not followed, so a link to a file outside the workdir does not snapshot that outside file.
- Steps that run at the same time share one workdir. `swag undo --to STEP` restores the tree from the moment that step started, which also reverts later edits, including edits from a step that ran in parallel after that snapshot. `auto_rollback` has the same effect.
- Memory writes and the append-only action log are not rolled back. The undo ledger itself is rewritten when a compensation is marked done; it is not an append-only audit log. `$SWAG_HOME/actions.jsonl` still is.
- Snapshots record bytes. They do not record why the agent did the work, and they are not a substitute for committing the result you meant to keep.

## Action log

`$SWAG_HOME/actions.jsonl` is append-only. `swag safety log` prints it. `swag safety policy` prints the autonomy level, the risk rules, active plugin grants, and any grants suspended because the plugin is disabled. `swag safety grant` and `swag safety revoke` edit grants. Rewriting active grants keeps the `suspended` object, so a manual grant does not drop a disabled plugin's saved permissions.

Secrets are redacted before they are stored: `sk-...` keys, bearer tokens, AWS-style access key ids, GitHub tokens, `password=` / `token=` / `api_key=` assignments, and any value under a secret-named key.

## MCP client

`build_mcp_client(settings)` reads `$SWAG_HOME/mcp.json`, which uses the Claude Code `.mcp.json` shape:

```json
{
  "mcpServers": {
    "local": {
      "command": "python",
      "args": ["server.py", "${WORKSPACE:-.}"],
      "env": {"API_TOKEN": "${API_TOKEN}"}
    },
    "remote": {
      "type": "http",
      "url": "https://example.com/mcp",
      "headers": {"Authorization": "Bearer ${API_TOKEN}"}
    }
  }
}
```

`${VAR}`, `${VAR:-default}` (unset or empty), and `${VAR-default}` (unset) are expanded when the client connects, not when the file is saved. `swag mcp list` does not print env or header values.

Supported transports are stdio and streamable HTTP. The official `mcp` package is optional (`pip install 'swag-bot[mcp]'`).

Tools are adapted to the shared `Tool` model as `server__tool`. `MCPToolRegistry` is a `ToolRegistry` over the client. `call_tool` builds an `ActionRequest` and asks the `PermissionPolicy` before the server runs. Pass the safety policy and prompter into `build_mcp_client` from the composition root; this package does not import `swag_bot.safety`.

```text
swag mcp list
swag mcp tools [SERVER]
swag mcp add NAME --command CMD --arg ARG --env KEY=VALUE
swag mcp add NAME --url URL --transport http --header Key=Value
swag mcp remove NAME
```

## MCP server

`swag serve-mcp` speaks stdio by default. `swag serve-mcp --http` (or `swag mcp serve --http`) serves streamable HTTP on `127.0.0.1:8765`.

Tools:

| Tool | Behavior |
| --- | --- |
| `swag_run_task` | `goal` in, summary out. The callable is injected. This package does not import the core loop. |
| `swag_list_skills` | JSON list of `{name, description}` from an injected provider. This package does not import the plugin loader. |

With no runner configured, `swag_run_task` returns a short message instead of failing closed on a missing core. The root `swag serve-mcp` command (and `swag mcp serve`) installs the real plan-do-verify runner and the plugin skill list. This package still does not import `core` or `plugins`; the callables are injected from the composition root.

`swag run` passes this package's sandbox and permission policy into the loop, and passes the same policy into `build_mcp_client`. The loop asks the policy before every tool call, including MCP tools. A second prompt is not shown for those MCP calls. A hard deny (`decide` returns `deny`) is still enforced, by the loop and again by the MCP client.

## Interface addition

`MCPServerSpec.headers: dict[str, str]` defaults to `{}`. It carries streamable-HTTP headers from `.mcp.json`. Older specs that omit it still validate.
