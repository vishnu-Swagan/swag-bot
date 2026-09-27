# Plugins

Swag Bot loads plugins in the Claude Cowork / Claude Code layout. A plugin is
a directory. The manifest is `.claude-plugin/plugin.json`. Skills, slash
commands, sub-agents, and MCP servers live next to it.

The loader parses those files into the shared models in
`swag_bot.interfaces`. It does not start MCP servers, run hooks, or apply
LSP settings. The MCP client (another package) receives `MCPServerSpec`
values and is the component that connects.

## Layout

```
my-plugin/
  .claude-plugin/
    plugin.json
  .mcp.json
  skills/
    my-skill/
      SKILL.md
      references/
      scripts/
      assets/
  commands/
    my-command.md
  agents/
    my-agent.md
```

Paths in the manifest are relative to the plugin root and must stay inside
it. `..` is rejected. A missing optional directory is fine. An explicit path
that does not exist is an error.

`swag plugin validate ./my-plugin` checks the manifest, skills, commands,
agents, and MCP config.

## Manifest

`.claude-plugin/plugin.json` uses the Claude Code field names: `name`,
`displayName`, `version`, `description`, `author`, `homepage`, `repository`,
`license`, `keywords`, `defaultEnabled`, `skills`, `commands`, `agents`,
`hooks`, `mcpServers`, `outputStyles`, `lspServers`, `userConfig`,
`channels`, `experimental`, and `dependencies`.

Unknown keys are kept. Claude Code ignores unknown keys, which is why the
Swag Bot extension can live in the same file.

`permissions` is that extension. It is a list of capability names the plugin
needs. Built-in names:

| Name | Meaning |
| --- | --- |
| `filesystem.read` | Read files |
| `filesystem.write` | Write files |
| `shell` | Run commands |
| `network` | Outbound connections |
| `mcp` | Talk to the plugin's MCP servers |
| `secrets` | Read credentials from the environment |

Other dotted names such as `com.example.deploy` are allowed. Names with
spaces are rejected. Unknown names are treated as risky at install time.

`author` may be a string or `{"name", "email", "url"}`. `dependencies` may
be a list of names or `{"name", "version"}` objects.

`skills`, `commands`, and `agents` are a path or a list of paths. When they
are omitted, Swag Bot uses `./skills`, `./commands`, and `./agents` if those
directories exist.

`mcpServers` is either a path (usually `./.mcp.json`) or an inline object.
When the field is omitted, a `.mcp.json` file at the plugin root is used if
it is there.

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "What this plugin adds.",
  "author": {"name": "Your Name"},
  "license": "MIT",
  "skills": "./skills/",
  "commands": "./commands/",
  "agents": "./agents/",
  "mcpServers": "./.mcp.json",
  "permissions": ["network", "mcp"]
}
```

`name` is 1-64 characters and must not contain spaces or slashes.

## Skills

Skills follow the Agent Skills open standard (https://agentskills.io/specification).
Each skill is a directory. The directory name matches the frontmatter `name`.
`SKILL.md` starts with YAML frontmatter:

```markdown
---
name: my-skill
description: What it does and when to use it. Mention the words a user would say.
license: MIT
compatibility: Optional notes about tools or network access. Max 500 characters.
metadata:
  author: your-name
  version: "0.1.0"
allowed-tools: Read
---

Instructions for the agent. Keep this file focused.
Point at `references/`, `scripts/`, and `assets/` for detail.
```

`name` is 1-64 characters: lowercase letters, digits, and single hyphens.
`description` is 1-1024 characters and should say both what the skill does
and when to use it. The description is what the skill selector sees.

Swag Bot loads skills in three steps:

1. At discovery, only the frontmatter is read. The markdown body is not kept.
2. `Skill.instructions()` reads the body when the skill is selected.
3. `Skill.resources()` lists files under `scripts/`, `references/`, and
   `assets/`. `Skill.read_resource()` reads one of them.

The frontmatter parser covers mappings, one nested mapping level, string
lists, and `|` / `>` block scalars. It does not need PyYAML.

### Standalone skills

These directories are scanned in addition to plugins:

- `.agents/skills/<name>/SKILL.md` under the current working directory
- `$SWAG_HOME/skills/<name>/SKILL.md` (`~/.swag/skills/` unless `SWAG_HOME` is set)

`swag skill list` prints name, description, and location. It does not print
skill bodies. If a plugin skill and a standalone skill share a name, the
plugin skill is the one the registry returns.

## Slash commands

`commands/*.md` becomes a slash command. The file name is the command name
(`commands/gh-issue.md` is `gh-issue`). A nested file uses a colon
(`commands/git/commit.md` is `git:commit`). Frontmatter `name` overrides that.

```markdown
---
description: Draft a GitHub issue from the text after the command
argument-hint: "[title and context]"
allowed-tools: Read
---

Draft a GitHub issue about $ARGUMENTS.
```

Discovery returns the description and leaves `body` empty. Invoking the
command reads the body and replaces every `$ARGUMENTS` with the text the
user passed. If the body does not contain `$ARGUMENTS` and the user did pass
text, that text is appended.

## Sub-agents

`agents/*.md` is a sub-agent definition:

```markdown
---
name: issue-triage
description: Triage a GitHub issue into a short summary and a next step.
tools: Read
model: inherit
---

You triage one GitHub issue. Do not post the result unless asked.
```

The body stays empty until the agent is loaded. Swag Bot does not run the
agent by itself. The registry exposes it as an `AgentDefinition` for the
core loop.

## MCP connectors

`.mcp.json` is the usual Claude Code MCP file:

```json
{
  "mcpServers": {
    "github": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"
      }
    }
  }
}
```

An `url` field selects a remote transport. `type` or `transport` may be
`stdio`, `http`, `sse`, or `ws` (`streamable-http` is stored as `http`).
When it is omitted, a `command` is `stdio` and a `url` is `http`.
`headers` is kept for streamable HTTP (`Authorization`, and other string
headers). Values may be `${VAR}` references. The loader does not expand them.

Put secrets in environment-variable references (`${GITHUB_PERSONAL_ACCESS_TOKEN}`
or the host environment via Docker `-e`). The loader does not expand those
references and does not start the process. The example plugin
`plugins/example-github-helper/` points at the official GitHub MCP image
`ghcr.io/github/github-mcp-server` this way.

## Install and the registry

```bash
swag plugin install ./my-plugin
swag plugin install https://github.com/you/my-plugin.git
swag plugin install you/my-plugin
swag plugin install you/my-plugin@v1.2.0
swag plugin list
swag plugin info my-plugin
swag plugin enable my-plugin
swag plugin disable my-plugin
swag plugin remove my-plugin
swag skill list
```

`install` prints the requested permissions and asks before copying. The
question goes through the `ApprovalPrompter` interface. `--yes` prints the
same permissions and skips the question.

Approving the prompt, or passing `--yes`, writes those permissions into
`$SWAG_HOME/grants.json` using the safety grant format
(`{"plugins": {"<name>": ["<permission>", ...]}}`).
The permission policy then allows an action tagged with that plugin when the
action needs one of those permissions. Permissions the plugin did not request
stay a hard deny. A grant does not lower a `destructive` risk and does not
prompt less often than the autonomy level.

A denial installs nothing. The plugin is not copied, the registry is not
changed, and no grants are written.

Accepted plugins are copied to `$SWAG_HOME/plugins/<name>/`. The registry is
`$SWAG_HOME/plugins/registry.json`:

```json
{
  "version": 1,
  "plugins": [
    {
      "name": "my-plugin",
      "version": "0.1.0",
      "enabled": true,
      "source": "you/my-plugin",
      "permissions": ["network", "mcp"],
      "installed_at": "2026-09-27T00:00:00+00:00"
    }
  ]
}
```

`defaultEnabled: false` installs the plugin turned off and stores the
approved permissions as suspended grants, so tagged actions stay denied
until `enable`. `disable` keeps the files, drops the plugin from discovery,
and suspends its grants for the same reason. `enable` applies those grants
again. `remove` deletes the copy and revokes the grants, including any that
were suspended. The plugins package does not import the safety package; the
root `swag` command injects the grant store.

`plugin_dirs` in
`$SWAG_HOME/config.toml` is also searched. A plugin found there wins over an
installed copy with the same name, so a checkout you are editing is the one
that loads.

`discover_plugins(settings)` and `load_plugin(root)` are the public
factories. `build_registry(settings)` returns a `PluginRegistry`: loaded
plugins, skill metadata, slash commands, sub-agents, MCP specs, and
`select_skills(goal)`. The selector is keyword overlap between the goal and
each skill's name and description. It does not call a model.

`swag run` calls `select_skills` for the goal and appends the matching
`SKILL.md` bodies to the planner prompt. It also merges each enabled
plugin's MCP servers with `~/.swag/mcp.json` (a config entry with the same
name wins) and registers those tools next to `read_file`, `write_file`, and
`run_shell`.

## Marketplaces

A marketplace is a git repository (or a local directory) with
`.claude-plugin/marketplace.json`:

```json
{
  "name": "my-plugins",
  "owner": {"name": "Your Name", "email": "you@example.com"},
  "metadata": {"pluginRoot": "./plugins"},
  "plugins": [
    {
      "name": "my-plugin",
      "source": "./plugins/my-plugin",
      "description": "What it adds",
      "version": "0.1.0"
    },
    {
      "name": "other-plugin",
      "source": {"source": "github", "repo": "you/other-plugin", "ref": "v1.0.0"},
      "description": "Fetched from GitHub"
    }
  ]
}
```

`swag plugin install ./my-marketplace --plugin my-plugin` reads that catalog.
A marketplace with one plugin does not need `--plugin`. Sources:

| Source | Meaning |
| --- | --- |
| `"./plugins/my-plugin"` | Directory inside the marketplace. Relative to the marketplace root, not to `.claude-plugin/`. |
| `"my-plugin"` with `metadata.pluginRoot` | `pluginRoot` is prepended. |
| `{"source": "github", "repo": "owner/repo", "ref": "v1"}` | Clone `https://github.com/owner/repo`. |
| `{"source": "url", "url": "https://example.com/plugin.git", "ref": "v1"}` | Clone a git URL. |
| `{"source": "git-subdir", "url": "...", "path": "plugins/my-plugin"}` | Clone, then use a subdirectory. |

`npm` and `pip` sources are recognized and refused. `strict` defaults to
true, which means the plugin directory must contain `plugin.json`. The
marketplace entry name must match that file. `strict: false` synthesizes a
manifest from the marketplace entry when `plugin.json` is absent.
`defaultEnabled` on the marketplace entry overrides the plugin manifest.

Install a marketplace the same way as a plugin: a local path, a git URL, or
`owner/repo[@ref]`.

## Publishing

1. Build the directory above. Keep secrets out of the files. Reference
   environment variables instead.
2. Run `swag plugin validate .` from the plugin root.
3. Push the directory to a public git repository. The repository root should
   be the plugin root, or a marketplace root whose `marketplace.json` points
   at the plugin.
4. Users install with `swag plugin install you/repo` or
   `swag plugin install you/marketplace --plugin my-plugin`.

The project license is MIT. Do not ship a plugin that vendors AGPL, SSPL, or
other network-copyleft code into Swag Bot itself. A plugin the user installs
is their choice. The example in this repository is MIT.

To publish through a signed gallery instead of a raw git install, see
[GALLERY.md](GALLERY.md). `swag gallery install` verifies a minisign signature
and runs a static scan before this permission prompt. `swag plugin install`
is unchanged and does not require a signature, so a local checkout can still
be installed while you are editing it.

## Compatibility with Claude Cowork and Claude Code

The same directory loads in both places when you follow the Claude layout.

| Topic | Claude Code / Cowork | Swag Bot |
| --- | --- | --- |
| Manifest | `.claude-plugin/plugin.json` | Same fields. Extra keys are preserved. |
| `permissions` | Ignored (unknown field). | Shown at install, stored on the registry row, and written to `grants.json` when the user approves or passes `--yes`. |
| Skills | Agent Skills `SKILL.md` | Same frontmatter rules and the same three loading steps. |
| Commands | `commands/*.md`, `$ARGUMENTS` | Same. |
| Agents | `agents/*.md` | Parsed into `AgentDefinition`. Not executed here. |
| MCP | `.mcp.json` / `mcpServers` | Parsed into `MCPServerSpec`. Not connected here. |
| Hooks and LSP | May run inside Claude. | Stored on the manifest when present. Not run. |
| Marketplace | `.claude-plugin/marketplace.json` | Relative, `github`, `url`, and `git-subdir` sources. `npm` and `pip` are refused. |
| Where it is installed | Claude's plugin cache. | `$SWAG_HOME/plugins/<name>/` plus `registry.json`. |
| Standalone skills | Claude also scans `.claude/skills` and `~/.claude/skills`. | `.agents/skills` and `$SWAG_HOME/skills` only. A Claude skill directory is not trusted just because it is on disk. |
| Install confirmation | Claude's own trust dialog. | `ApprovalPrompter`, or `--yes`. |

`plugins/example-github-helper/` is a complete sample: a manifest with
`permissions`, one skill, one slash command, one sub-agent, and `.mcp.json`
aimed at the official GitHub MCP server without a token in the file.
