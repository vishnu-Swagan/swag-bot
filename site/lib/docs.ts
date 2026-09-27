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
        text: `curl -fsSL https://raw.githubusercontent.com/vishnu-Swagan/swag-bot/main/scripts/install.sh | sh\n\n# Windows PowerShell\nirm https://raw.githubusercontent.com/vishnu-Swagan/swag-bot/main/scripts/install.ps1 | iex`,
      },
      {
        type: "note",
        text: `v0.2 is on main. A tagged release is coming. The scripts install from Git with uv, then run swag setup --auto. pip install swag-bot is not published yet. Until PyPI is on, the git install the scripts use is: ${GIT_INSTALL}`,
      },
      { type: "h", text: "Setup" },
      {
        type: "p",
        text: "swag setup --auto detects an exported API key, an Ollama model of at least 7B, or a running local server (LM Studio, Jan, llama.cpp, llamafile, GPT4All). Otherwise it asks before pulling qwen2.5:7b (about 4.7 GB), or prints a free-cloud menu. It does not install Ollama for you. --yes skips the model question. --dry-run prints the decision and writes nothing. --base-url points at another OpenAI-compatible server and does not fall through to the cloud menu. If that server is down, or every model id that states a size is under 7B, setup stops with an error.",
      },
      {
        type: "code",
        text: `swag setup --auto\nswag setup --auto --base-url http://localhost:1234/v1\nswag doctor\nswag doctor --json`,
      },
      { type: "h", text: "Local model with Ollama" },
      {
        type: "p",
        text: "Ollama is the default provider. The default model name is llama3.2. No API key is sent. The client talks to 127.0.0.1:11434 unless OLLAMA_HOST or model.api_base says otherwise.",
      },
      {
        type: "code",
        text: `ollama pull llama3.2\nswag model set ollama/llama3.2\nswag model probe\nswag run "Summarize the files in this directory"`,
      },
      { type: "h", text: "A smaller model" },
      {
        type: "p",
        text: "qwen2.5:3b on plain CPU, with the small-model harness, finished a fib task in 78 seconds, in one step, and printed 55. Without the harness that task was still failing after about 4 minutes. swag setup --auto does not select a 3B tag when the size is visible; swag model probe is how you profile the model you did set.",
      },
      {
        type: "code",
        text: "swag model set ollama/qwen2.5:3b\nswag model probe",
      },
      { type: "h", text: "What a run writes" },
      {
        type: "p",
        text: "swag run writes an output directory. That directory holds plan.json, action-log.jsonl, run.jsonl, and summary.md. The default path is ./swag-output/<UTC timestamp>. Pass --output-dir to choose another folder. --record writes a portable run bundle at <output-dir>/bundle. swag replay re-executes that bundle from the saved model responses. The default --tools mode is rerun, so tools run again; --tools recorded returns the saved tool results.",
      },
      {
        type: "code",
        text: 'swag run "Write a short status note" --autonomy auto --output-dir ./swag-output/demo --record',
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
        text: "Local runs stay on your hardware. swag setup --auto probes a server that is already running. It does not install LM Studio, Jan, llama.cpp, llamafile, or GPT4All. The default base URLs in docs/MODELS.md are localhost:1234 (LM Studio), localhost:1337 (Jan), localhost:8080 (llama.cpp and llamafile), and localhost:4891 (GPT4All). Ollama uses http://127.0.0.1:11434.",
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
        text: "docs/MODELS.md lists the free-plan defaults setup writes: Gemini gemini-2.5-flash, Groq groq/llama-3.3-70b-versatile via the litellm provider, OpenRouter openrouter/free, Cerebras cerebras/gpt-oss-120b, and Mistral mistral/mistral-small-latest. Keys are read from the environment or from $SWAG_HOME/provider-keys.env. swag doctor and swag model list print set or unset for OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, and OPENROUTER_API_KEY, and never the value. GROQ_API_KEY, CEREBRAS_API_KEY, and MISTRAL_API_KEY are read by LiteLLM and redacted from errors; they are not rows in those commands. swag doctor --json reports ready and reason and does not include a secret. swag model set writes config.toml and does not write secrets.",
      },
      {
        type: "code",
        text: `swag model list\nswag model test\nswag model probe\nswag model set ollama/llama3.2\nswag model set gemini/gemini-2.5-flash\nswag model set openrouter/openrouter/free\nswag model set litellm/groq/llama-3.3-70b-versatile`,
      },
      { type: "h", text: "Keys the free-cloud menu uses" },
      {
        type: "ul",
        items: [
          "GEMINI_API_KEY",
          "GROQ_API_KEY",
          "OPENROUTER_API_KEY",
          "CEREBRAS_API_KEY",
          "MISTRAL_API_KEY",
          "OPENAI_API_KEY and ANTHROPIC_API_KEY are also detected when already exported",
        ],
      },
      {
        type: "p",
        text: "The models extra installs LiteLLM. The install scripts request swag-bot[mcp,models] from Git. The CLI does not read a .env file. Export keys yourself, or let swag setup --auto store a free-plan key in provider-keys.env with mode 0600.",
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
        text: "Stdio is the default. --http serves streamable HTTP on 127.0.0.1:8765. The server offers swag_run_task, swag_start_task, swag_task_status, swag_task_result, swag_list_skills, and swag_setup_status. Write and shell approval uses MCP elicitation. swag setup --grant can preapprove a risk for those sessions.",
      },
      {
        type: "code",
        text: `swag serve-mcp\nswag serve-mcp --http --port 8765\nswag install-mcp\nswag install-mcp --client cursor`,
      },
      { type: "h", text: "Clients" },
      {
        type: "p",
        text: "swag install-mcp prints the Claude Code command, the Cursor and VS Code install links, and the Gemini, Claude Desktop, and ChatGPT notes. --client accepts claude, cursor, vscode, gemini, desktop, chatgpt, or all. The Chrome side panel connects with swag extension install. The extension source is extension/ in the repository.",
      },
      {
        type: "note",
        text: "This page does not paste a generated deeplink. Run swag install-mcp on your machine so the link matches the launcher the current tree uses.",
      },
    ],
  },
  {
    slug: "specs",
    title: "Specs",
    lede: "Two contracts: the evidence a step must cite, and the bundle a run leaves behind.",
    sourceLabel: "docs/spec",
    sourceHref: `${REPO}/tree/main/docs/spec`,
    blocks: [
      { type: "h", text: "Evidence contract" },
      {
        type: "p",
        text: "The open evidence contract is docs/spec/evidence-contract.md (spec id swag-evidence-contract, version 1.0). Each run writes <output-dir>/run.jsonl. Check kinds in that spec are file_exists, file_absent, file_contains, command, exit_code, and json_schema. A pass has to cite evidence ids.",
      },
      {
        type: "ul",
        items: [
          "A step carries checks the harness runs itself.",
          "Tool results are evidence and have ids.",
          "A pass verdict cites those ids.",
          "A model claim that contradicts the evidence does not pass.",
        ],
      },
      {
        type: "p",
        text: 'Worked example: the model said "All tests passed". The script exited 1. The cited evidence contradicted the claim, so the step was not done.',
      },
      {
        type: "link",
        href: `${REPO}/blob/main/docs/spec/evidence-contract.md`,
        label: "Evidence contract on GitHub",
      },
      { type: "h", text: "Run bundle" },
      {
        type: "p",
        text: "The open bundle spec is docs/spec/run-bundle.md (spec id swag-run-bundle, version 1.0). swag run --record writes the bundle at <output-dir>/bundle. swag replay <bundle> re-executes it from saved model responses. The default tool mode is rerun. --tools recorded returns the saved tool results. --mode live calls a model and compares. swag bundle inspect prints the manifest. swag bundle export --output report.zip zips it. Secrets are redacted before the bundle is written.",
      },
      {
        type: "code",
        text: `swag run "Write a short status note" --output-dir ./swag-output/demo --record\nswag replay ./swag-output/demo/bundle\nswag bundle inspect ./swag-output/demo/bundle\nswag bundle export ./swag-output/demo/bundle --output report.zip`,
      },
      {
        type: "note",
        text: "With --output-dir ./swag-output/demo, --record writes ./swag-output/demo/bundle. A run that omits --output-dir prints Bundle: under ./swag-output/<UTC timestamp>/bundle.",
      },
      {
        type: "link",
        href: `${REPO}/blob/main/docs/spec/run-bundle.md`,
        label: "Run bundle spec on GitHub",
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
    lede: "Commands and flags from this tree. v0.2 is on main. A tagged release is coming.",
    sourceLabel: "src/swag_bot",
    sourceHref: `${REPO}/tree/main/src/swag_bot`,
    blocks: [
      { type: "h", text: "swag" },
      {
        type: "ul",
        items: [
          "swag version — print the package version.",
          "swag doctor — print the active config. API keys in the table are set or unset, never the value.",
          "swag doctor --json — readiness report with ready and reason. It does not include a secret, and it returns before --probe.",
          "swag doctor --probe — profile the configured model and print the cached capability report.",
          "swag setup --auto [--yes] [--dry-run] [--json] [--grant TEXT] [--base-url URL] — detect a model or record an MCP preapproval. With no flags, setup is --auto.",
          "swag install-mcp [--client claude|cursor|vscode|gemini|desktop|chatgpt|all]",
          "swag run GOAL — plan, act, and check a task.",
          "swag undo [--run ID] [--to STEP] — restore the workspace, including files a shell command changed. Snapshots live under $SWAG_HOME/undo.",
          "swag replay BUNDLE [--mode recorded|live] [--model TEXT] [--output-dir PATH] [--tools rerun|recorded]",
        ],
      },
      { type: "h", text: "swag run" },
      {
        type: "code",
        text: `swag run GOAL [--autonomy TEXT] [--model TEXT] [--output-dir PATH]\n  [--max-steps INTEGER] [--dry-run] [--concurrency INTEGER]\n  [--max-attempts INTEGER] [--engine TEXT] [--strict-plan]\n  [--memory-mode ask|auto|off] [--evidence|--no-evidence]\n  [--taint-mode escalate|block|off] [--escalate|--no-escalate]\n  [--harness auto|off|tiny|standard|frontier]\n  [--record] [--bundle PATH]`,
      },
      {
        type: "ul",
        items: [
          "GOAL is required and must not be empty.",
          "--autonomy overrides the configured level: ask-always, ask-risky, ask-irreversible, or auto. The default is ask-risky.",
          "--output-dir defaults to ./swag-output/<UTC timestamp> and receives plan.json, action-log.jsonl, run.jsonl, and summary.md.",
          "--max-steps defaults to 8. --max-attempts defaults to 2. --concurrency defaults to 4. Each must be at least 1.",
          "--strict-plan stops when the model plan cannot be parsed instead of falling back to one step.",
          "--evidence is on unless config or --no-evidence says otherwise. --no-evidence lets a step pass on the model's word.",
          "--escalate asks when a step is uncertain and can require a jury before an irreversible action.",
          "--harness auto probes a real model once and caches the profile. tiny, standard, and frontier pick a scaffold directly.",
          "--record writes a run bundle at <output-dir>/bundle. --bundle PATH writes that directory instead and implies --record.",
          "--engine is python (default), graphbit, or auto.",
        ],
      },
      { type: "h", text: "swag bundle" },
      {
        type: "ul",
        items: [
          "swag bundle inspect BUNDLE [--json]",
          "swag bundle export BUNDLE --output FILE.zip",
        ],
      },
      { type: "h", text: "swag model" },
      {
        type: "ul",
        items: [
          "swag model list — active provider/model, OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, and OPENROUTER_API_KEY as set or unset, and local Ollama names when the daemon answers.",
          "swag model test [PROMPT] — one short prompt.",
          "swag model probe [--force] [--json] — cache JSON, tool-call, and context scores.",
          "swag model set PROVIDER/MODEL — write config.toml. Example: swag model set ollama/llama3.2.",
        ],
      },
      { type: "h", text: "swag plugin, swag skill, and swag gallery" },
      {
        type: "ul",
        items: [
          "swag plugin list, install PATH [--yes] [--plugin NAME], enable, disable, remove, info, show, validate PATH",
          "swag skill list",
          "swag skill learn PATH [--evidence FILE] [--replay FILE]",
          "swag skill candidates [--all], promote ID, reject ID, recheck NAME",
          "swag gallery search [QUERY], info NAME, install NAME. --index is a JSON file or http(s) URL. When omitted, the command uses SWAG_GALLERY_INDEX.",
          "swag gallery keygen, sign, and bundle for a publisher. See docs/GALLERY.md.",
        ],
      },
      { type: "h", text: "swag safety" },
      {
        type: "ul",
        items: [
          "swag safety policy — show the autonomy policy.",
          "swag safety log [--limit N] — the append-only action log. The default file is $SWAG_HOME/actions.jsonl.",
          "swag safety grant PLUGIN PERMISSION",
          "swag safety revoke PLUGIN PERMISSION",
        ],
      },
      { type: "h", text: "swag mcp, swag serve-mcp, and the extension" },
      {
        type: "ul",
        items: [
          "swag mcp list, swag mcp tools, swag mcp add, swag mcp remove",
          "swag serve-mcp [--http] [--host 127.0.0.1] [--port 8765]",
          "swag extension install, remove, status, host",
        ],
      },
      { type: "h", text: "swag memory" },
      {
        type: "ul",
        items: [
          "swag memory add, search, list, forget.",
          "The default backend is SQLite at ~/.swag/memory.db. A JSON file or an agentmemory server are the other backends.",
        ],
      },
      {
        type: "note",
        text: "ask-risky prompts for anything that is not a pure read. ask-always prompts for every action, including reads. ask-irreversible prompts at the point of no return. auto does not prompt. Actions are still logged, and a hard deny still applies. The default answer to a prompt is no.",
      },
    ],
  },
];

export function getDoc(slug: string): DocArticle | undefined {
  return DOCS.find((doc) => doc.slug === slug);
}
