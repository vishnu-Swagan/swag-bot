/** Product copy. Claims stay inside the owner's brief and the repository docs. */

export const PRODUCT = {
  name: "Swag Bot",
  cli: "swag",
  versionLabel: "0.2",
  taggedRelease: "0.1.0",
  author: "Vishnu M",
  githubUser: "vishnu-Swagan",
  license: "MIT",
} as const;

export const GITHUB_URL = "https://github.com/vishnu-Swagan/swag-bot";
export const GITHUB_USER_URL = "https://github.com/vishnu-Swagan";
export const RELEASES_URL = `${GITHUB_URL}/releases`;
export const RELEASE_010_URL = `${GITHUB_URL}/releases/tag/v0.1.0`;
export const DOCS_REPO_URL = `${GITHUB_URL}/tree/main/docs`;
export const README_URL = `${GITHUB_URL}/blob/main/README.md`;
export const CHANGELOG_URL = `${GITHUB_URL}/blob/main/CHANGELOG.md`;
export const CONTRIBUTING_URL = `${GITHUB_URL}/blob/main/CONTRIBUTING.md`;
export const LICENSE_URL = `${GITHUB_URL}/blob/main/LICENSE`;
export const MODELS_DOC_URL = `${GITHUB_URL}/blob/main/docs/MODELS.md`;
export const PLUGINS_DOC_URL = `${GITHUB_URL}/blob/main/docs/PLUGINS.md`;
export const SAFETY_DOC_URL = `${GITHUB_URL}/blob/main/docs/SAFETY.md`;
export const ARCHITECTURE_URL = `${GITHUB_URL}/blob/main/docs/ARCHITECTURE.md`;
export const EXAMPLE_PLUGIN_URL = `${GITHUB_URL}/tree/main/plugins/example-github-helper`;
export const DISCUSSIONS_URL = `${GITHUB_URL}/discussions`;
export const ISSUES_URL = `${GITHUB_URL}/issues`;
export const STARS_API = "https://api.github.com/repos/vishnu-Swagan/swag-bot";

export const OWNER = {
  entity: "[OWNER TO CONFIRM: legal entity name]",
  email: "[OWNER TO CONFIRM: contact email]",
  jurisdiction: "[OWNER TO CONFIRM: governing-law jurisdiction]",
} as const;

export const DESCRIPTION =
  "Swag Bot is a free, MIT-licensed general AI agent. It plans a goal, carries out the step, and will not mark that step done unless a check cites real tool evidence.";

export const INSTALL = {
  unix: {
    id: "unix",
    label: "macOS / Linux",
    command:
      "curl -fsSL https://raw.githubusercontent.com/vishnu-Swagan/swag-bot/main/scripts/install.sh | sh",
    comingSoon: false,
  },
  windows: {
    id: "windows",
    label: "Windows",
    command:
      "irm https://raw.githubusercontent.com/vishnu-Swagan/swag-bot/main/scripts/install.ps1 | iex",
    comingSoon: false,
  },
  pip: {
    id: "pip",
    label: "pip · coming soon",
    command: "pip install swag-bot",
    comingSoon: true,
  },
} as const;

export const INSTALL_TABS = [INSTALL.unix, INSTALL.windows, INSTALL.pip] as const;

/** Git install used by the install scripts until PyPI publishing is turned on. */
export const GIT_INSTALL =
  'uv tool install "swag-bot[mcp,models] @ git+https://github.com/vishnu-Swagan/swag-bot"';

export const NAV = [
  { href: "/features", label: "Features" },
  { href: "/docs", label: "Docs" },
  { href: "/plugins", label: "Plugins" },
  { href: "/changelog", label: "Changelog" },
] as const;

export type Feature = {
  slug: string;
  index: string;
  title: string;
  summary: string;
  fact: string;
  body: string[];
  demo: DemoKind;
};

export type DemoKind =
  | "evidence"
  | "handoff"
  | "install"
  | "harness"
  | "undo"
  | "sign"
  | "taint"
  | "skill"
  | "jury"
  | "bundle";

export const FEATURES: readonly Feature[] = [
  {
    slug: "proof-checks",
    index: "01",
    title: "Proof-based step checking",
    summary:
      "A step is done only when the verdict cites evidence. An open spec defines the checks.",
    fact: 'A model once claimed "All tests passed". The script had exited 1. The check failed the step.',
    body: [
      "Swag Bot attaches machine-checkable checks to a step and runs them in the harness. The model's own sentence is not the verdict.",
      "A pass has to cite evidence ids from the tool results. If the claim and the evidence disagree, the step is not done.",
      "The evidence contract is open. The readable summary is on the specs page, and the repository docs are the source that will keep the format.",
    ],
    demo: "evidence",
  },
  {
    slug: "step-handoff",
    index: "02",
    title: "Step handoff and honest failure",
    summary: "Later steps receive what earlier steps actually produced. A failure stays a failure.",
    fact: "A step that does not pass is reported as failed. The run does not quietly treat it as done.",
    body: [
      "When a step finishes, the next step can see that step's outputs. Work does not depend on the model remembering a file it never recorded.",
      "Honest failure means a broken plan or a failed check is shown as such. The run does not paper over it with a success line.",
    ],
    demo: "handoff",
  },
  {
    slug: "one-command-setup",
    index: "03",
    title: "One-command install and setup",
    summary: "One command installs the swag CLI and sets it up.",
    fact: "scripts/install.sh and scripts/install.ps1 install from Git, then run swag setup --auto. pip install swag-bot is not on PyPI yet.",
    body: [
      "macOS and Linux use scripts/install.sh. Windows uses scripts/install.ps1. The script asks before it installs uv, then runs swag setup --auto.",
      "pip install swag-bot is the command once PyPI publishing is on. It does not work today. The install scripts install from Git instead.",
    ],
    demo: "install",
  },
  {
    slug: "small-model-harness",
    index: "04",
    title: "Small-model harness",
    summary: "A tighter harness so a small local model can finish a task on plain CPU.",
    fact: "qwen2.5:3b on plain CPU finished a fib task in 78 s, in 1 step, printing 55. The same task was still failing after about 4 minutes without the harness.",
    body: [
      "The harness is there so a small model is not asked to improvise the whole job in one loose prompt.",
      "That fib run is one measured task, not a general benchmark. This site does not turn it into a score against other agents.",
    ],
    demo: "harness",
  },
  {
    slug: "undo-ledger",
    index: "05",
    title: "Undo ledger",
    summary: "State-changing actions are recorded so a run can be undone.",
    fact: "The ledger is the record you use to roll a run back, instead of guessing which files the agent touched.",
    body: [
      "Swag Bot keeps an undo ledger of the actions a run took. Reversible work can be walked back from that record.",
      "Irreversible actions are a different class. Those go through the uncertainty questions and the jury, described with feature 09.",
    ],
    demo: "undo",
  },
  {
    slug: "signed-gallery",
    index: "06",
    title: "Signed plugin gallery",
    summary: "Plugins are signed with minisign and passed through a scanner.",
    fact: "Signing uses minisign. A scanner runs over gallery plugins. The public catalog on this website is not populated yet.",
    body: [
      "Plugins stay compatible with the Claude Cowork plugin and skills format, plus MCP.",
      "The gallery page on this site is a placeholder. Every card is marked coming soon. The example plugin in the repository is a local sample, not a signed listing.",
    ],
    demo: "sign",
  },
  {
    slug: "taint-firewall",
    index: "07",
    title: "Taint firewall",
    summary: "Tool output is untrusted, so prompt injection in a file or page does not get to steer the agent.",
    fact: "Content that arrives from a tool is tainted. The firewall treats it as data, not as new instructions.",
    body: [
      "A page, a file, or a tool result can contain text that tries to override the task. The firewall keeps that text on the untrusted side of the boundary.",
      "This site does not quote third-party lab scores as if they were Swag Bot's. The claim here is the firewall itself.",
    ],
    demo: "taint",
  },
  {
    slug: "verified-skills",
    index: "08",
    title: "Verified skill learning",
    summary: "A skill is kept only after evidence and a replay gate.",
    fact: "Learning is gated. A skill needs evidence from a run, then a replay, before it is kept.",
    body: [
      "Swag Bot can learn a skill from a run that actually worked. The evidence ids are part of that decision.",
      "A replay gate runs the skill again before it is promoted. A lucky trace is not enough on its own.",
    ],
    demo: "skill",
  },
  {
    slug: "uncertainty-jury",
    index: "09",
    title: "Uncertainty questions and a jury",
    summary: "Irreversible actions pause for questions, then a jury, before they proceed.",
    fact: "The jury blocked a fake $500 payment.",
    body: [
      "When the agent is unsure, it asks. Irreversible actions do not sail through on a single confident sentence.",
      "A jury reviews those high-stakes actions. In one case it stopped a fake payment of $500.",
    ],
    demo: "jury",
  },
  {
    slug: "run-bundles",
    index: "10",
    title: "Portable run bundles",
    summary: "A run packs into a bundle you can move, with secrets redacted, and replay offline.",
    fact: "Bundles redact secrets and can be replayed without the network.",
    body: [
      "A run bundle is a portable record of the run: what was planned, what ran, and which evidence ids were cited.",
      "Secret redaction runs before the bundle is written. Offline replay reads that bundle without calling a model provider.",
    ],
    demo: "bundle",
  },
];

export function getFeature(slug: string): Feature | undefined {
  return FEATURES.find((feature) => feature.slug === slug);
}

export const LOCAL_MODELS = [
  {
    id: "ollama",
    name: "Ollama",
    note: "Default provider. No API key. swag setup --auto uses an installed Ollama tag of at least 7B, or asks before pulling qwen2.5:7b. The fib run used qwen2.5:3b.",
    command: "swag setup --auto",
  },
  {
    id: "lm-studio",
    name: "LM Studio",
    note: "Local OpenAI-compatible server. Prompts stay on this machine. Default base URL in docs/MODELS.md is http://localhost:1234/v1.",
    command: "swag setup --auto --base-url http://localhost:1234/v1",
  },
  {
    id: "jan",
    name: "Jan",
    note: "Local server. docs/MODELS.md lists http://localhost:1337/v1.",
    command: "swag setup --auto --base-url http://localhost:1337/v1",
  },
  {
    id: "llama-cpp",
    name: "llama.cpp / llamafile",
    note: "docs/MODELS.md lists both at http://localhost:8080/v1.",
    command: "swag setup --auto --base-url http://localhost:8080/v1",
  },
  {
    id: "gpt4all",
    name: "GPT4All",
    note: "Local API server. docs/MODELS.md lists http://localhost:4891/v1.",
    command: "swag setup --auto --base-url http://localhost:4891/v1",
  },
] as const;

export const CLOUD_MODELS = [
  {
    id: "gemini",
    name: "Gemini",
    note: "Free cloud plan. Setup stores GEMINI_API_KEY and uses gemini-2.5-flash. Prompts go to Google under Gemini's terms.",
    command: "swag model set gemini/gemini-2.5-flash",
  },
  {
    id: "groq",
    name: "Groq",
    note: "Free cloud plan through LiteLLM. The model string in docs/MODELS.md is groq/llama-3.3-70b-versatile. Prompts leave your machine.",
    command: "swag model set litellm/groq/llama-3.3-70b-versatile",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    note: "Free router. docs/MODELS.md uses openrouter/free and OPENROUTER_API_KEY.",
    command: "swag model set openrouter/openrouter/free",
  },
  {
    id: "cerebras",
    name: "Cerebras",
    note: "Free cloud plan through LiteLLM. docs/MODELS.md lists cerebras/gpt-oss-120b.",
    command: "swag model set litellm/cerebras/gpt-oss-120b",
  },
  {
    id: "mistral",
    name: "Mistral",
    note: "Free cloud plan through LiteLLM. docs/MODELS.md lists mistral/mistral-small-latest.",
    command: "swag model set litellm/mistral/mistral-small-latest",
  },
] as const;

export const INTEGRATIONS = [
  { name: "Claude", detail: "Cowork plugins, skills, and MCP" },
  { name: "Claude Desktop", detail: "MCP and the Cowork plugin layout" },
  { name: "Cursor", detail: "Connect the MCP server" },
  { name: "VS Code", detail: "Connect the MCP server" },
  { name: "Gemini", detail: "Connect over MCP" },
  { name: "Chrome", detail: "Side-panel extension" },
] as const;

export const FAQ = [
  {
    q: "Is Swag Bot free?",
    a: "Yes. The project is MIT-licensed and free. Local models run on your machine. Free cloud plans (Gemini, Groq, OpenRouter, Cerebras, Mistral) are free tiers from those providers, under their terms, not a bill from Swag Bot.",
  },
  {
    q: "Does the CLI send telemetry?",
    a: "No. The CLI has no telemetry and runs locally. This website does not set tracking cookies or load analytics. If you choose a cloud model, that provider receives the prompts you send.",
  },
  {
    q: "What counts as done?",
    a: 'A step is done when a check cites evidence. A model once answered "All tests passed" while the script exited 1. That step did not pass.',
  },
  {
    q: "Will a small model finish anything?",
    a: "qwen2.5:3b on plain CPU finished a fib task in 78 seconds, in one step, and printed 55. Without the small-model harness, that task was still failing after about 4 minutes. That is one task, not a leaderboard.",
  },
  {
    q: "What did the jury stop?",
    a: "Uncertainty questions plus a jury gate irreversible actions. The jury blocked a fake $500 payment.",
  },
  {
    q: "Where is the plugin gallery?",
    a: "Signing (minisign) and a scanner are part of the product. The gallery page on this site is still a placeholder, and every listing is marked coming soon.",
  },
  {
    q: "Where do I report a security issue?",
    a: "Use the contact on the security page. A SECURITY.md file is not in the repository yet. Please do not file a public issue for an undisclosed vulnerability.",
  },
  {
    q: "Is the output professional advice?",
    a: "No. Model output can be wrong. You are responsible for what you approve and what the agent does. Read the disclaimer.",
  },
] as const;

export type CompareRow = {
  name: string;
  href: string;
  focus: string;
  license: string;
  proof: string;
  undo: string;
  supply: string;
  stars: string;
};

export const COMPARE_AS_OF = "2026-09-28";

export const COMPARE: readonly CompareRow[] = [
  {
    name: "Swag Bot",
    href: GITHUB_URL,
    focus: "General agent. Local models or free cloud plans.",
    license: "MIT",
    proof: "Proof-based checks. A pass cites evidence ids. A contradicting claim does not pass.",
    undo: "Undo ledger.",
    supply: "Signed gallery (minisign + scanner). Site catalog is not populated yet.",
    stars: "Live count on the GitHub button. Not a snapshot.",
  },
  {
    name: "OpenClaw",
    href: "https://github.com/openclaw/openclaw",
    focus: "Self-hosted personal assistant. Tools, skills, plugins, ClawHub.",
    license: "MIT. Copyright OpenClaw Foundation.",
    proof: "Not described as per-step evidence checks in the sources read for the 2026-09-28 report.",
    undo: "Not covered in the sources used for this table.",
    supply:
      "Snyk scanned 3,984 skills on ClawHub and skills.sh: 13.4% had at least one critical issue, and 76 malicious payloads were confirmed. The write-up says publishing had no code signing.",
    stars: "390,651",
  },
  {
    name: "Hermes Agent",
    href: "https://github.com/NousResearch/hermes-agent",
    focus: "Learning loop, skills, session search, messaging gateway.",
    license: "MIT. Nous Portal is a paid model option.",
    proof:
      "The report checked the README only. That README does not describe verification gating before a skill is kept.",
    undo: "Not covered in the sources used for this table.",
    supply: "Not covered beyond the skill-learning note above.",
    stars: "249,445",
  },
  {
    name: "Goose",
    href: "https://github.com/aaif-goose/goose",
    focus: "General local agent. Desktop, CLI, and API.",
    license: "Apache-2.0. Contributed to the Agentic AI Foundation.",
    proof:
      "Recipes can include shell success checks with retry. They are user-written, cover the whole recipe, and a failed check resets the session.",
    undo: "Not described as a shell-side-effect ledger in the source used here.",
    supply: "MCP extensions. Signing was not part of the recipe source that was read.",
    stars: "54,706",
  },
  {
    name: "OpenHands",
    href: "https://github.com/OpenHands/OpenHands",
    focus: "Coding agent with a critic and trajectory replay.",
    license: "MIT core. The enterprise directory is source-available.",
    proof:
      "The critic scores trajectories with a learned model. Refinement is off by default. The CLI critic is free only with the OpenHands model provider.",
    undo: "Trajectory replay is documented. It is not described as an undo ledger for shell side effects.",
    supply: "Not the subject of the critic docs that were read.",
    stars: "89,300",
  },
  {
    name: "Claude Code",
    href: "https://github.com/anthropics/claude-code",
    focus: "Coding agent. Checkpoints, hooks, and an OS sandbox.",
    license: "Proprietary. The repository license is all rights reserved, commercial terms.",
    proof: "Stop hooks can gate on a command. They are user-configured. Only exit code 2 blocks.",
    undo: "Checkpoints do not track Bash changes, per the checkpointing docs.",
    supply: "Cowork plugins can come from a git marketplace. Signing was not documented on the page the report read.",
    stars: "148,320",
  },
  {
    name: "Gemini CLI",
    href: "https://github.com/google-gemini/gemini-cli",
    focus: "Coding CLI with checkpointing and extensions.",
    license: "Apache-2.0.",
    proof: "Not described as generated per-step evidence checks in the sources used here.",
    undo: "Checkpointing uses a shadow git repo and /restore. It is off by default.",
    supply: "Extensions install from a GitHub URL.",
    stars: "107,166",
  },
];

export const COMPARE_NOTES: readonly { id: string; text: string; href?: string }[] = [
  {
    id: "stars",
    text: `Star counts are from the GitHub API on ${COMPARE_AS_OF}, as recorded in the competitive report prepared that day. They change. They are not a quality score. Swag Bot's count is loaded live in the header and is left out of this snapshot.`,
  },
  {
    id: "openclaw-host",
    text: "OpenClaw README: tools run on the host for the main session unless you configure sandboxing.",
    href: "https://github.com/openclaw/openclaw",
  },
  {
    id: "snyk",
    text: "Snyk, ToxicSkills: 3,984 skills scanned on ClawHub and skills.sh; 13.4% with at least one critical issue; 76 malicious payloads confirmed.",
    href: "https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/",
  },
  {
    id: "hermes",
    text: "Hermes: the report checked the README only, and says that file does not describe verification gating before a skill is kept.",
    href: "https://github.com/NousResearch/hermes-agent",
  },
  {
    id: "goose",
    text: "Goose recipe reference: shell success checks with retry, written by the user for the whole recipe.",
    href: "https://github.com/block/goose/blob/58f3cc9e/documentation/docs/guides/recipes/recipe-reference.md",
  },
  {
    id: "openhands",
    text: "OpenHands CLI critic docs: learned trajectory critic, refinement off by default, free on the CLI only with the OpenHands model provider.",
    href: "https://docs.openhands.dev/openhands/usage/cli/critic.md",
  },
  {
    id: "claude-checkpoint",
    text: "Claude Code checkpointing docs: checkpoints do not track Bash changes.",
    href: "https://code.claude.com/docs/en/checkpointing",
  },
  {
    id: "claude-hooks",
    text: "Claude Code hooks guide: Stop hooks are user-configured; only exit code 2 blocks.",
    href: "https://code.claude.com/docs/en/hooks-guide",
  },
  {
    id: "claude-license",
    text: "Claude Code LICENSE.md: all rights reserved, commercial terms.",
    href: "https://raw.githubusercontent.com/anthropics/claude-code/main/LICENSE.md",
  },
  {
    id: "gemini",
    text: "Gemini CLI checkpointing is documented and the report records the default as off (general.checkpointing.enabled: false).",
    href: "https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/checkpointing.md",
  },
];

export const LOOP = [
  {
    id: "plan",
    index: "01",
    title: "Plan",
    lede: "A goal becomes steps, and each step gets checks the harness can run.",
    points: [
      "You state the goal in swag run.",
      "The plan is a list of steps, not a single open-ended reply.",
      "Checks are part of the step, so “done” has a definition before the model starts talking.",
    ],
  },
  {
    id: "act",
    index: "02",
    title: "Act",
    lede: "The step runs with tools. Results are stored as evidence with ids.",
    points: [
      "Built-in tools in the repository are read_file, write_file, and run_shell.",
      "Exit codes and output are evidence, not a paragraph the model wrote about them.",
      "The next step can receive the previous step’s outputs.",
    ],
  },
  {
    id: "prove",
    index: "03",
    title: "Prove",
    lede: "A pass must cite evidence. A claim that contradicts it does not pass.",
    points: [
      "The verdict points at evidence ids.",
      "“All tests passed” with exit code 1 is a failed step.",
      "You keep a record you can undo, bundle, and replay.",
    ],
  },
] as const;

export type SearchEntry = {
  title: string;
  href: string;
  group: string;
  keywords: string;
};

export function searchEntries(): SearchEntry[] {
  const pages: SearchEntry[] = [
    { title: "Home", href: "/", group: "Pages", keywords: "swag bot agent install" },
    { title: "Features", href: "/features", group: "Pages", keywords: "proof undo firewall jury" },
    { title: "Docs", href: "/docs", group: "Pages", keywords: "quickstart documentation" },
    { title: "Plugins", href: "/plugins", group: "Pages", keywords: "gallery skills cowork coming soon" },
    { title: "Changelog", href: "/changelog", group: "Pages", keywords: "releases 0.1.0 0.2" },
    { title: "Security", href: "/security", group: "Pages", keywords: "disclosure vulnerability" },
    { title: "Community", href: "/community", group: "Pages", keywords: "contributing issues discussions" },
    { title: "Brand", href: "/brand", group: "Pages", keywords: "trademark logo name usage" },
    { title: "Terms of Use", href: "/legal/terms", group: "Legal", keywords: "terms legal" },
    { title: "Privacy Policy", href: "/legal/privacy", group: "Legal", keywords: "privacy telemetry cookies" },
    { title: "Disclaimer", href: "/legal/disclaimer", group: "Legal", keywords: "warranty advice" },
    { title: "MIT license", href: "/legal/license", group: "Legal", keywords: "mit open source" },
    { title: "Acceptable Use", href: "/legal/acceptable-use", group: "Legal", keywords: "abuse policy" },
  ];
  const features: SearchEntry[] = FEATURES.map((feature) => ({
    title: feature.title,
    href: `/features/${feature.slug}`,
    group: "Features",
    keywords: `${feature.summary} ${feature.fact}`,
  }));
  const docs: SearchEntry[] = [
    ["Quickstart", "quickstart", "install ollama first run"],
    ["Models", "models", "ollama gemini groq local cloud"],
    ["Plugins and skills", "plugins", "cowork skills slash commands"],
    ["MCP setup", "mcp", "cursor claude vscode serve-mcp"],
    ["Specs", "specs", "evidence contract run bundle"],
    ["CLI reference", "cli", "swag run doctor plugin"],
  ].map(([title, slug, keywords]) => ({
    title,
    href: `/docs/${slug}`,
    group: "Docs",
    keywords,
  }));
  return [...pages, ...features, ...docs];
}
