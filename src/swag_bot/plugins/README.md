# plugins

**Owner:** the plugins agent.

**Edit only:** `src/swag_bot/plugins/`, `tests/plugins/`, the top-level
`plugins/` examples, and `docs/PLUGINS.md`.

Read `docs/ARCHITECTURE.md` before touching a shared file. `interfaces.py`
changes stay additive. `AgentDefinition` and `PluginRegistry` were added there
so other packages can consume plugins without importing this one.

## What lives here

A loader and installer for Claude Cowork / Claude Code plugins.

- `load_plugin` reads `.claude-plugin/plugin.json` with `PluginManifest`.
- Skills, slash commands, and sub-agents load progressively: frontmatter at
  discovery, markdown bodies when invoked, bundled files via `read_resource`.
- `.mcp.json` is parsed into `MCPServerSpec` values. Servers are not started.
- `discover_plugins` reads `settings.plugin_dirs` and enabled installs.
- Standalone skills are discovered in `.agents/skills/` and `$SWAG_HOME/skills/`.
- `build_registry` returns a `PluginRegistry` (skills, commands, agents, MCP
  specs, and a keyword skill selector).
- Installs are copied to `$SWAG_HOME/plugins/<name>/` and recorded in
  `registry.json`. Install shows permissions and asks an `ApprovalPrompter`.
  An approved install records those permissions through an injected
  `GrantStore`. This package does not import `safety`.

`docs/PLUGINS.md` is the authoring guide.

## CLI

`swag plugin list|install|enable|disable|remove|info|show|validate`

`swag skill list`

`swag gallery search|info|install|keygen|sign|bundle` checks a static gallery
index. Signature verification and the static scanner run before the existing
install permission prompt. See `docs/GALLERY.md`.
