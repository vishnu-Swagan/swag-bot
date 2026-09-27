import { GIT_INSTALL, GITHUB_URL } from "@/lib/site";

export type Block =
  | { type: "p"; text: string }
  | { type: "h"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "code"; text: string }
  | { type: "note"; text: string }
  | { type: "link"; href: string; label: string };

export type DocArticle = {
  slug: string;
  title: string;
  lede: string;
  sourceLabel: string;
  sourceHref: string;
  blocks: Block[];
};

const REPO = GITHUB_URL;

export const DOCS: readonly DocArticle[] = [
  {
    slug: "quickstart",
    title: "Quickstart",
    lede: "Install the swag CLI, point it at a local model, and run a goal.",
    sourceLabel: "Repository README",
    sourceHref: `${REPO}/blob/main/README.md`,
    blocks: [
      {
        type: "p",
        text: "Python 3.11 or newer. The one-command paths are the shell installer, the PowerShell installer, and pip.",
      },
      {
        type: "code",
        text: `curl -fsSL https://raw.githubusercontent.com/vishnu-Swagan/swag-bot/main/install.sh | bash\n\n# Windows PowerShell\nirm https://raw.githubusercontent.com/vishnu-Swagan/swag-bot/main/install.ps1 | iex\n\npip install swag-bot`,
      },
      {
        type: "note",
        text: `The tagged release recorded in the repository changelog is 0.1.0. The README also documents this pinned git install: ${GIT_INSTALL}`,
      },
      { type: "h", text: "Local model with Ollama" },
      {
        type: "p",
        text: "Ollama is the default provider in the repository. The default model name there is llama3.2. No API key is sent. The client talks to 127.0.0.1:11434 unless OLLAMA_HOST or model.api_base says otherwise.",
      },
      {
        type: "code",
        text: `ollama pull llama3.2\nswag doctor\nswag model set ollama/llama3.2\nswag run "Summarize the files in this directory"`,
      },
      { type: "h", text: "A smaller model" },
      {
        type: "p",
        text: "qwen2.5:3b on plain CPU, with the small-model harness, finished a fib task in 78 seconds, in one step, and printed 55. Without the harness that task was still failing after about 4 minutes.",
      },
      {
        type: "code",
        text: "swag model set ollama/qwen2.5:3b",
      },
      { type: "h", text: "What a run writes" },
      {
        type: "p",
        text: "swag run writes an output directory. In the current repository that directory holds plan.json, action-log.jsonl, and summary.md. The default path is ./swag-output/<UTC timestamp>. Pass --output-dir to choose another folder.",
      },
      {
        type: "code",
        text: 'swag run "Write a short status note" --autonomy auto --output-dir ./swag-output/demo',
      },
      {
        type: "link",
        href: "/docs/models",
        label: "Models",
      },
    ],
  },
  {
    slug: "models",
    title: "Models",
    lede: "Run on your hardware, or on a free cloud plan. You choose where the prompt goes.",
    sourceLabel: "docs/MODELS.md",
    sourceHref: `${REPO}/blob/main/docs/MODELS.md`,
    blocks: [
      { type: "h", text: "On your machine" },
      {
        type: "ul",
        items: [
          "Ollama",
          "LM Studio",
          "Jan",
          "llama.cpp / llamafile",
          "GPT4All",
        ],
      },
      {
        type: "p",
        text: "Local runs stay on your hardware. The repository's native client is Ollama: provider ollama, default model llama3.2, base URL from model.api_base, then OLLAMA_HOST, then http://127.0.0.1:11434.",
      },
      { type: "h", text: "Free cloud plans" },
      {
        type: "ul",
        items: ["Gemini", "Groq", "OpenRouter", "Cerebras", "Mistral"],
      },
      {
        type: "p",
        text: "Choosing a cloud provider sends your prompts to that provider. Their terms govern the processing. Swag Bot does not add its own telemetry on top.",
      },
      { type: "h", text: "Providers the repository client names today" },
      {
        type: "p",
        text: "docs/MODELS.md lists ollama, and through optional LiteLLM: openai, anthropic, gemini, openrouter, and litellm. The litellm provider passes the model string through. Keys are read from the environment at request time. swag doctor prints set or unset and never the value. swag model set writes config.toml and does not write secrets.",
      },
      {
        type: "code",
        text: `swag model list\nswag model test\nswag model set ollama/llama3.2\nswag model set gemini/<model>\nswag model set openrouter/<author>/<model>`,
      },
      {
        type: "note",
        text: "Angle-bracket placeholders are not real model ids. Use the id your provider account actually offers. This page does not invent one.",
      },
      { type: "h", text: "Keys the doctor command knows" },
      {
        type: "ul",
        items: [
          "OPENAI_API_KEY",
          "ANTHROPIC_API_KEY",
          "GEMINI_API_KEY",
          "OPENROUTER_API_KEY",
        ],
      },
      {
        type: "p",
        text: "The models extra installs LiteLLM: python -m pip install \"swag-bot[models] @ git+https://github.com/vishnu-Swagan/swag-bot.git\". The CLI does not read a .env file. Export keys yourself.",
      },
    ],
  },
  {
    slug: "plugins",
    title: "Plugins and skills",
    lede: "A plugin is a directory in the Claude Cowork layout. The same tree loads in Cowork and Claude Code.",
    sourceLabel: "docs/PLUGINS.md",
    sourceHref: `${REPO}/blob/main/docs/PLUGINS.md`,
    blocks: [
      {
        type: "p",
        text: "The folder holds .claude-plugin/plugin.json, skills/*/SKILL.md, commands/*.md, agents/*.md, and an optional .mcp.json. Swag Bot's extra field is permissions. Claude Code ignores unknown fields, so the file still loads there.",
      },
      {
        type: "code",
        text: `swag plugin validate ./plugins/example-github-helper\nswag plugin install ./plugins/example-github-helper\nswag plugin list\nswag skill list`,
      },
      {
        type: "p",
        text: "swag plugin install prints the requested permissions and asks before it copies anything. --yes prints the same list and skips the question. Installed plugins live in $SWAG_HOME/plugins/. Approving an install writes those permissions into $SWAG_HOME/grants.json. Declining writes no grants.",
      },
      {
        type: "ul",
        items: [
          "swag plugin enable and swag plugin disable suspend or restore grants.",
          "swag plugin remove revokes them.",
          "swag safety grant <plugin> <permission> adds one permission by hand.",
          "swag skill list prints name, description, and location. It does not load skill bodies.",
        ],
      },
      { type: "h", text: "Signed gallery" },
      {
        type: "p",
        text: "Gallery plugins are signed with minisign and scanned. The catalog on this website is a placeholder and every card is marked coming soon. The example-github-helper directory in the repository is a sample you can validate locally. It is not a signed public listing.",
      },
      {
        type: "link",
        href: "/plugins",
        label: "Plugin gallery",
      },
    ],
  },
  {
    slug: "mcp",
    title: "MCP setup",
    lede: "Swag Bot talks to MCP servers, and swag serve-mcp exposes Swag Bot as one.",
    sourceLabel: "README, MCP section",
    sourceHref: `${REPO}/blob/main/README.md#mcp`,
    blocks: [
      {
        type: "p",
        text: "Configure servers in ~/.swag/mcp.json, using the Claude Code .mcp.json shape. ${VAR} placeholders expand when a client connects, not when the file is saved. swag mcp list does not print env or header values.",
      },
      {
        type: "code",
        text: `swag mcp add local --command python --arg server.py\nswag mcp add remote --url https://example.com/mcp --transport http --header "Authorization=Bearer \${API_TOKEN}"\nswag mcp list\nswag mcp tools`,
      },
      { type: "h", text: "Serve Swag Bot" },
      {
        type: "p",
        text: "Stdio is the default. --http serves streamable HTTP on 127.0.0.1:8765. The server offers swag_run_task (run a goal, return the summary) and swag_list_skills (name and description). Install the mcp extra first.",
      },
      {
        type: "code",
        text: `swag serve-mcp\nswag serve-mcp --http --port 8765`,
      },
      { type: "h", text: "Clients" },
      {
        type: "p",
        text: "Connect from Claude, Claude Desktop, Cursor, VS Code, and Gemini by adding that MCP server in the client's own settings. A Chrome side-panel extension is part of the product. This site does not link a store listing, because none is published here.",
      },
      {
        type: "note",
        text: "There is no one-click install deeplink on this site. Use the client you already have, and point it at swag serve-mcp.",
      },
    ],
  },
  {
    slug: "specs",
    title: "Specs",
    lede: "Two contracts: the evidence a step must cite, and the bundle a run leaves behind.",
    sourceLabel: "Repository docs",
    sourceHref: `${REPO}/tree/main/docs`,
    blocks: [
      { type: "h", text: "Evidence contract" },
      {
        type: "p",
        text: "The evidence spec is open. This page is the readable summary. The repository docs are where the format lives as it is maintained. This summary does not invent field names that the repository has not published.",
      },
      {
        type: "ul",
        items: [
          "A step carries checks the harness can run itself.",
          "Tool results are evidence and have ids.",
          "A pass verdict cites those ids.",
          "A model claim that contradicts the evidence does not pass.",
        ],
      },
      {
        type: "p",
        text: 'Worked example: the model said "All tests passed". The script exited 1. The cited evidence contradicted the claim, so the step was not done.',
      },
      { type: "h", text: "Run bundle" },
      {
        type: "ul",
        items: [
          "A bundle is a portable record of a run.",
          "Secrets are redacted before the bundle is written.",
          "The bundle can be replayed offline, without calling a model provider.",
        ],
      },
      {
        type: "p",
        text: "In the tagged 0.1.0 tree, swag run already writes plan.json, action-log.jsonl, and summary.md into the output directory. The action log redacts secrets. The bundle is the portable, replayable form of a run on top of that record.",
      },
      {
        type: "link",
        href: "/features/proof-checks",
        label: "Proof-based step checking",
      },
    ],
  },
  {
    slug: "cli",
    title: "CLI reference",
    lede: "Commands that exist in this repository. Feature pages describe the v0.2 behavior. They do not add flags that this tree does not have.",
    sourceLabel: "src/swag_bot",
    sourceHref: `${REPO}/tree/main/src/swag_bot`,
    blocks: [
      { type: "h", text: "swag" },
      {
        type: "ul",
        items: [
          "swag version — print the package version.",
          "swag doctor — print the active config. Secret env vars show as set or unset, never the value.",
          "swag run GOAL — plan, act, and check a task.",
        ],
      },
      { type: "h", text: "swag run" },
      {
        type: "code",
        text: `swag run GOAL [--autonomy TEXT] [--model TEXT] [--output-dir PATH]\n  [--max-steps INTEGER] [--dry-run] [--concurrency INTEGER]\n  [--max-attempts INTEGER] [--engine TEXT]`,
      },
      {
        type: "ul",
        items: [
          "GOAL is required and must not be empty.",
          "--autonomy overrides the configured level: ask-always, ask-risky, or auto. The repository default is ask-risky.",
          "--model overrides the configured model name.",
          "--output-dir defaults to ./swag-output/<UTC timestamp> and receives plan.json, action-log.jsonl, and summary.md.",
          "--max-steps defaults to 8. --max-attempts defaults to 2. --concurrency defaults to 4. Each must be at least 1.",
          "--dry-run plans only and does not run steps.",
          "--engine is python (default), graphbit, or auto. GraphBit is optional. If it is not installed, graphbit falls back to the Python scheduler and says so.",
        ],
      },
      { type: "h", text: "swag model" },
      {
        type: "ul",
        items: [
          "swag model list — active provider/model, cloud keys as set or unset, and local Ollama names when the daemon answers.",
          "swag model test [PROMPT] — one short prompt.",
          "swag model set PROVIDER/MODEL — write config.toml. Example: swag model set ollama/llama3.2.",
        ],
      },
      { type: "h", text: "swag plugin and swag skill" },
      {
        type: "ul",
        items: [
          "swag plugin list",
          "swag plugin install PATH [--yes] [--plugin NAME]",
          "swag plugin enable NAME, disable NAME, remove NAME",
          "swag plugin info NAME, show NAME, validate PATH",
          "swag skill list",
        ],
      },
      { type: "h", text: "swag safety" },
      {
        type: "ul",
        items: [
          "swag safety policy — show the autonomy policy.",
          "swag safety log [--limit N] — show the append-only action log. The default file is $SWAG_HOME/actions.jsonl.",
          "swag safety grant PLUGIN PERMISSION",
          "swag safety revoke PLUGIN PERMISSION",
        ],
      },
      { type: "h", text: "swag mcp and swag serve-mcp" },
      {
        type: "ul",
        items: [
          "swag mcp list, swag mcp tools",
          "swag mcp add NAME [--command ...] [--arg ...] [--url ...] [--transport stdio|http] [--header Key=Value] [--env KEY=VALUE]",
          "swag mcp remove NAME",
          "swag serve-mcp [--http] [--host 127.0.0.1] [--port 8765]",
        ],
      },
      { type: "h", text: "swag memory" },
      {
        type: "ul",
        items: [
          "swag memory add, search, list, forget.",
          "The default backend in the repository is SQLite at ~/.swag/memory.db. A JSON file or an agentmemory server are the other backends.",
        ],
      },
      {
        type: "note",
        text: "Autonomy ask-risky prompts for anything that is not a pure read. ask-always prompts for every action, including reads. auto does not prompt. Actions are still logged, and a hard deny still applies. The default answer to a prompt is no.",
      },
    ],
  },
];

export function getDoc(slug: string): DocArticle | undefined {
  return DOCS.find((doc) => doc.slug === slug);
}
