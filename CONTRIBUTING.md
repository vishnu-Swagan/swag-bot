# Contributing

Swag Bot is MIT licensed. Contributions should stay MIT-compatible. Do not
copy AGPL, SSPL, or other network-copyleft source into the repository, and
do not add those licenses as dependencies. Optional extras such as GraphBit
(Apache-2.0) are imported only when the user asks for them.

## Setup

Python 3.11 or newer.

```bash
python -m pip install -e ".[dev]"
```

API keys stay in the environment. Copy the names from `.env.example` if you
need a reminder. Do not commit `.env`, tokens, or real credentials. Tests
and docs use placeholders only.

`SWAG_HOME` overrides `~/.swag`. The test suite sets it to a temporary
directory.

## Checks

```bash
ruff check .
mypy
pytest
```

CI runs ruff, mypy, and pytest on Python 3.11 and 3.12. It does not install
the optional `models`, `mcp`, `sandbox`, or `graphbit` extras. mypy is
`strict` on the `swag_bot` package. The optional `mcp` and `anyio` imports
use `ignore_missing_imports` because a base install does not provide them.
Tests are not type-checked: two modules are both named `test_tools`.

Docker sandbox tests skip themselves when the `docker` CLI is missing. MCP
client tests skip themselves when the `mcp` extra is not installed.

## Layout

Owned packages do not import each other. They depend on
`swag_bot.interfaces`, `swag_bot.config`, and `swag_bot.errors`.

`swag run` in `src/swag_bot/core/cli.py` is the composition root. It may call
the public factories:

| Factory | Module |
| --- | --- |
| `build_llm_client` | `swag_bot.models` |
| `build_memory_store` | `swag_bot.memory` |
| `build_sandbox`, `build_permission_policy`, `build_prompter` | `swag_bot.safety` |
| `build_mcp_client` | `swag_bot.mcp` |
| `build_registry`, `discover_plugins`, `load_plugin` | `swag_bot.plugins` |

`swag serve-mcp` passes a task runner and a skill provider into the MCP
server. The MCP package does not import the core loop or the plugin loader.

Changes to `interfaces.py` are additive. New fields need defaults. Do not
rename or remove protocols, and do not tighten a type so existing values stop
validating. New settings in `config.py` need defaults. Do not store secrets
there.

Unit tests should inject `tests/fakes.py` (`FakeLLMClient`, `FakeSandbox`,
`InMemoryMemoryStore`, `AutoApprovePrompter`) instead of a live model or a
prompt.

## Pull requests

Open a pull request against `main`. Describe what changed and how you tested
it. Keep the diff focused on one area when you can: `core`, `plugins`,
`safety` / `mcp`, or `models` / `memory`.

## Releases

`project.version` in `pyproject.toml` and `__version__` in
`src/swag_bot/__init__.py` are the package version. Keep them the same, and
record the release in `CHANGELOG.md`.

Pushing a `v*` tag (for example `v0.1.0`) runs
`.github/workflows/release.yml`. The tag must match the package version. The
workflow builds an sdist and a wheel, checks them with twine, and creates a
GitHub Release with those files attached.

PyPI upload is off unless the repository variable `PUBLISH_PYPI` is `true`.
If that variable is set and `PYPI_API_TOKEN` is missing, the upload is skipped
and the GitHub Release still succeeds.
