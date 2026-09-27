# plugins

**Owner:** the plugins agent.

**Edit only:** `src/swag_bot/plugins/` and `tests/plugins/`.

Read `docs/ARCHITECTURE.md` before touching a shared file. `interfaces.py` changes stay additive.

## What goes here

A loader for Claude Cowork / Claude Code plugins.

- Discover plugin roots from `settings.plugin_dirs`. Also accept a directory that contains `.claude-plugin/plugin.json`.
- Parse that JSON with `PluginManifest.from_plugin_json`. `permissions` is the Swag Bot extension; every other field mirrors the Claude manifest. Unknown keys must keep loading.
- Agent Skills: build `SkillMeta` from `SKILL.md` frontmatter at discovery time (level 1). `Skill.instructions()` reads the body (level 2). `Skill.read_resource()` reads `scripts/`, `references/`, and `assets/` (level 3). Do not add a required YAML dependency to the base install if you can parse the frontmatter without one; if you need PyYAML, put it in an optional extra.
- Slash commands from `commands/*.md` as `SlashCommand`. Leave `body` empty until the command runs.
- `discover_plugins` and `load_plugin` in `__init__.py` are the public entry points. Replace the `NotImplementedYet` stubs. Keep the names.

## CLI

`swag plugin list`, `swag plugin show`, and `swag plugin validate`. Add further subcommands on this Typer app. Keep the group name `plugin`.

## Status

Stub. The commands exit 2.
