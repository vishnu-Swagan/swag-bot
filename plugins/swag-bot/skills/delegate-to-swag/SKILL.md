---
name: delegate-to-swag
description: >
  Hand a long, checkable task to the local Swag Bot agent. Use when the user
  wants files written, a multi-step change carried out, or a result that can
  be verified on disk. Swag Bot plans, does the work, and checks it.
license: MIT
compatibility: Requires the Swag Bot MCP server from this plugin.
metadata:
  author: swag-bot
  version: "0.2.0"
allowed-tools: Read
---

# Delegate to Swag Bot

Use the `swag` MCP server for a task that should run on the user's machine
instead of only in this chat.

1. Call `swag_setup_status` first. If `ready` is false, tell the user the
   `reason`, including the `swag setup --auto` command it names, and stop.
   Do not invent a model key.
2. Prefer `swag_start_task`, then poll `swag_task_status` until `status` is
   not `running`, then read `swag_task_result`. Do this for any task that
   might take more than a minute, and for every task on a local model.
   Claude Code backgrounds an MCP call after 120 seconds
   (`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS`, default 120000). A backgrounded
   call plus a new one can hit a single-slot local Ollama server together
   and the run times out. Polling avoids that. Set
   `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` only when the user wants
   `swag_run_task` to stay in the foreground.
3. Use `swag_run_task` only for a short task on a fast model.
4. Read the tool result JSON. `status` is `met`, `not_met`, or `aborted`.
   `goal_checks` lists each check with `evidence_ids`. `output_dir` is the
   folder. `files` lists the files the user asked for, with `size` and, for
   a small text file, `content`. Quote that content. Do not invent file
   contents when `content` is missing or `exists` is false. A failure or
   abort sets the tool error flag.
5. If the result says the user declined the approval, say that and stop.
   The run is not met. If the result says an action was denied, show that
   text. Do not retry the same write in a loop. The user can allow it in
   the elicitation form, or preapprove a risk with `swag setup --grant write`
   in a terminal.
6. Report the summary Swag Bot returned. Do not claim a file changed unless
   the tool result says so.
