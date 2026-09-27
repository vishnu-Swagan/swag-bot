# safety

**Owner:** the safety and MCP agent. You also own `src/swag_bot/mcp/` and `tests/mcp/`.

**Edit only:** `src/swag_bot/safety/`, `src/swag_bot/mcp/`, `tests/safety/`, and `tests/mcp/`.

The narrow exception is the `serve-mcp` wrapper in `src/swag_bot/cli.py`: update it only to keep its options in sync with `mcp/cli.py`. Read `docs/ARCHITECTURE.md` before any other shared edit. `interfaces.py` changes stay additive.

## What goes here

- A `Sandbox`. `settings.sandbox.mode` is `local` (subprocess in a workdir), `docker` (image from `settings.sandbox.image`, network off unless `sandbox.network`), or `off` (refuse `run`). Run every file path through `resolve_sandbox_path`. On timeout return `CommandResult` with `timed_out=True` and `exit_code` 124 (`TIMEOUT_EXIT_CODE`).
- A `PermissionPolicy` for `settings.autonomy`. Use `default_requires_approval`. You may deny more often. Do not prompt less often than that helper.
- An `ApprovalPrompter` for real use. Tests use `AutoApprovePrompter` in `tests/fakes.py`.
- An append-only action log of `ActionLogEntry`. Redact secrets before they are stored. `approver` is `policy`, `user`, or `auto`.
- `build_sandbox`, `build_permission_policy`, and `build_prompter` in `__init__.py`. Keep those names.

`docker` is an optional extra (`pip install -e ".[sandbox]"`). Do not make it a required dependency.

## CLI

`swag safety log` and `swag safety policy`. Add subcommands on this Typer app.

## Status

Stub. The commands exit 2.
