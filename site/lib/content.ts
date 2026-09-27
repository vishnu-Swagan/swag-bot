/** Product facts for the landing page. Keep claims aligned with the repo docs. */

export const VERSION = "0.1.0";

export const GITHUB_URL = "https://github.com/vishnu-Swagan/swag-bot";
export const RELEASE_URL = `${GITHUB_URL}/releases/tag/v${VERSION}`;
export const DOCS_URL = `${GITHUB_URL}/tree/main/docs`;
export const README_URL = `${GITHUB_URL}/blob/main/README.md`;
export const PLUGIN_GUIDE_URL = `${GITHUB_URL}/blob/main/docs/PLUGINS.md`;
export const MODELS_DOC_URL = `${GITHUB_URL}/blob/main/docs/MODELS.md`;
export const SAFETY_DOC_URL = `${GITHUB_URL}/blob/main/docs/SAFETY.md`;
export const LICENSE_URL = `${GITHUB_URL}/blob/main/LICENSE`;
export const OLLAMA_URL = "https://ollama.com/";

/**
 * One-line install shown in the hero and the install section.
 * Switch this to `pip install swag-bot` once PyPI publishing is on.
 */
export const INSTALL_COMMAND =
  "pip install git+https://github.com/vishnu-Swagan/swag-bot@v0.1.0";

/** Exact pinned install from the README, after the v0.1.0 tag. */
export const PIP_PIN_COMMAND =
  'python -m pip install "swag-bot @ git+https://github.com/vishnu-Swagan/swag-bot.git@v0.1.0"';

/** README pipx install, with the v0.1.0 pin the README tells you to add. */
export const PIPX_COMMAND =
  'pipx install "swag-bot @ git+https://github.com/vishnu-Swagan/swag-bot.git@v0.1.0"';

export const OLLAMA_COMMANDS = `ollama pull llama3.2
swag doctor
swag run "Summarize the files in this directory"`;

export const MODEL_SET_COMMAND = "swag model set ollama/llama3.2";

export const FIRST_RUN_COMMAND =
  'swag run "Write a short status note" --autonomy auto --output-dir ./swag-output/demo';

export const EXTRA_COMMANDS = [
  {
    name: "models",
    detail: "LiteLLM, for OpenAI, Anthropic, Gemini, and OpenRouter",
    command:
      'python -m pip install "swag-bot[models] @ git+https://github.com/vishnu-Swagan/swag-bot.git@v0.1.0"',
  },
  {
    name: "mcp",
    detail: "Official MCP SDK, for the client and swag serve-mcp",
    command:
      'python -m pip install "swag-bot[mcp] @ git+https://github.com/vishnu-Swagan/swag-bot.git@v0.1.0"',
  },
  {
    name: "sandbox",
    detail: "Docker SDK, used when the docker CLI is not on PATH",
    command:
      'python -m pip install "swag-bot[sandbox] @ git+https://github.com/vishnu-Swagan/swag-bot.git@v0.1.0"',
  },
] as const;

export const NAV_LINKS = [
  { href: "#loop", label: "How it works" },
  { href: "#features", label: "Features" },
  { href: "#demo", label: "Demo" },
  { href: "#install", label: "Install" },
] as const;

export const LOOP_STAGES = [
  {
    id: "plan",
    index: "01",
    title: "Plan",
    color: "violet" as const,
    lede: "You give it a goal. Swag Bot turns that goal into steps.",
    points: [
      "It recalls matching memories before it plans.",
      "It adds plugin skills whose descriptions match the goal.",
      "Independent steps are marked so they can run together.",
    ],
  },
  {
    id: "do",
    index: "02",
    title: "Do",
    color: "coral" as const,
    lede: "It carries the steps out, and it asks before risky actions.",
    points: [
      "Built-in tools are read_file, write_file, and run_shell.",
      "MCP tools from your config and enabled plugins join them.",
      "The default autonomy is ask-risky: pure reads proceed, everything else asks. The default answer is no.",
    ],
  },
  {
    id: "verify",
    index: "03",
    title: "Verify",
    color: "mint" as const,
    lede: "It checks each step, then leaves you a record.",
    points: [
      "A step is done only when it ran and the check passed.",
      "A failed check is retried. The run can ask for a new plan, still within a step limit.",
      "You get plan.json, action-log.jsonl, and summary.md. A summary is saved to memory.",
    ],
  },
] as const;

export const FEATURES = [
  {
    id: "models",
    kicker: "Models",
    title: "Free local models, or your own key",
    href: MODELS_DOC_URL,
    linkLabel: "Models and memory",
    body: "Ollama is the default. The model is llama3.2, on your machine, and no API key is sent. Prefer a cloud model? Install the models extra and use LiteLLM.",
    facts: [
      { label: "Default", value: "ollama / llama3.2" },
      { label: "Local API", value: "127.0.0.1:11434" },
      { label: "Also", value: "OpenAI, Anthropic, Gemini, OpenRouter" },
    ],
  },
  {
    id: "safety",
    kicker: "Safety",
    title: "A sandbox, then a yes or a no",
    href: SAFETY_DOC_URL,
    linkLabel: "Safety and MCP",
    body: "Commands run in the task folder, with a timeout, and file paths cannot escape it. Docker is optional: a throwaway container with the network off unless you turn it on.",
    facts: [
      { label: "Sandbox", value: "local by default, or docker, or off" },
      { label: "Autonomy", value: "ask-always, ask-risky, auto" },
      { label: "Log", value: "Append-only, with secrets redacted" },
    ],
  },
  {
    id: "plugins",
    kicker: "Plugins",
    title: "The same folder Cowork already uses",
    href: PLUGIN_GUIDE_URL,
    linkLabel: "Plugin guide",
    body: "A plugin is a directory: .claude-plugin/plugin.json, skills, slash commands, agents, and an optional .mcp.json. That tree loads in Claude Cowork and Claude Code. Install asks before it copies anything.",
    facts: [
      { label: "Skills", value: "Agent Skills, loaded in three steps" },
      { label: "Commands", value: "Slash commands with $ARGUMENTS" },
      { label: "Install", value: "Asks before copying. Approval writes grants." },
    ],
  },
  {
    id: "mcp",
    kicker: "MCP",
    title: "Talks to servers, and can be one",
    href: `${README_URL}#mcp`,
    linkLabel: "MCP in the README",
    body: "The client speaks stdio and streamable HTTP. swag serve-mcp exposes Swag Bot itself, with swag_run_task and swag_list_skills. Install the mcp extra first.",
    facts: [
      { label: "Config", value: "~/.swag/mcp.json" },
      { label: "Serve", value: "stdio, or HTTP on 127.0.0.1:8765" },
      { label: "Secrets", value: "${VAR} expands on connect, not on save" },
    ],
  },
  {
    id: "memory",
    kicker: "Memory",
    title: "It looks back, then it writes the result down",
    href: `${MODELS_DOC_URL}#memory`,
    linkLabel: "Memory in the docs",
    body: "Before planning, a run searches what it already saved. Afterward it stores a summary. The default backend is SQLite on your machine. It does not use the network.",
    facts: [
      { label: "Default", value: "SQLite at ~/.swag/memory.db" },
      { label: "Also", value: "A JSON file, or an agentmemory server" },
      { label: "Search", value: "Best match first. An empty query returns nothing." },
    ],
  },
] as const;

export const DOCTOR_ROWS = [
  ["version", VERSION],
  ["config file", "absent, defaults in use"],
  ["model.provider", "ollama"],
  ["model.model", "llama3.2"],
  ["model.api_base", "(provider default)"],
  ["autonomy", "ask-risky"],
  ["memory.backend", "memory"],
  ["sandbox.mode", "local"],
  ["sandbox.network", "false"],
  ["OPENAI_API_KEY", "unset"],
  ["ANTHROPIC_API_KEY", "unset"],
  ["GEMINI_API_KEY", "unset"],
  ["OPENROUTER_API_KEY", "unset"],
] as const;

export const WALKTHROUGH_NOTE =
  "These doctor rows are the defaults when no config file exists. swag doctor prints set or unset for keys, and never the value. A real run’s steps come from the model, so they are not invented here. The command prints Planning:, then the summary, then Output: and the folder. That folder holds plan.json, action-log.jsonl, and summary.md.";
