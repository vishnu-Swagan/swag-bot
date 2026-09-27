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
  version: "0.1.0"
allowed-tools: Read
---

# Delegate to Swag Bot

Use the `swag` MCP server for a task that should run on the user's machine
instead of only in this chat.

1. Call `swag_setup_status` first. If `ready` is false, tell the user what
   `reason` says and stop. Do not invent a model key.
2. For a short task, call `swag_run_task` with the user's goal.
3. For a task that may take a while, call `swag_start_task`, then poll
   `swag_task_status` until it is `done` or `error`, and read `swag_task_result`.
4. If the tool result says the action was denied, show that text. Do not
   retry the same write in a loop. The user can allow it in the elicitation
   form, or preapprove a risk with `swag setup --grant write` in a terminal.
5. Report the summary Swag Bot returned. Do not claim a file changed unless
   the tool result says so.
