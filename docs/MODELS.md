# Models and memory

`swag setup --auto` can use a model you already have on this machine, or a
free cloud plan. The sections below are the user-facing choices. The rest of
this file is how the clients and the memory stores are built.

## Local and free cloud models

Checked against each project's docs on 2026-09-27. Setup probes; it does not
install these apps.

Order inside `swag setup --auto`:

1. A key that is already exported (or saved under `$SWAG_HOME`).
2. An Ollama tag of at least 7B that is already installed.
3. Another local OpenAI-compatible server that is already running.
4. A pull of `qwen2.5:7b` (about 4.7 GB) when Ollama is up and the machine has at least 6 GB of RAM. Setup asks first. A 3B model is not selected.
5. A short menu of free cloud plans, when nothing local is usable and no key is set.

### Local servers (free, private)

Prompts stay on this machine. Setup calls `GET /v1/models` with a short
timeout and configures LiteLLM's OpenAI-compatible route: provider
`litellm`, model `openai/<id>`, and `model.api_base` set to that server.

| App | Default base URL | Docs |
| --- | --- | --- |
| LM Studio | `http://localhost:1234/v1` | [OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat) |
| Jan | `http://localhost:1337/v1` | [Jan docs](https://www.jan.ai/docs) |
| llama.cpp server | `http://localhost:8080/v1` | [server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) |
| llamafile | `http://localhost:8080/v1` | [llamafile](https://github.com/mozilla-ai/llamafile) (same port as llama.cpp) |
| GPT4All API server | `http://localhost:4891/v1` | [Local API Server](https://github.com/nomic-ai/gpt4all/wiki/Local-API-Server) |
| Ollama | `http://127.0.0.1:11434` | [Ollama](https://ollama.com/) (`/api/tags`, not `/v1/models`) |

A model id under 7B is skipped when the size is visible in the id (for
example `llama3.2:3b`). If the id does not say the size, setup allows it and
says so. `swag model probe` is the small-model harness; this package does
not ship that command. When it is installed, the message tells you to run it.

Any other OpenAI-compatible server:

```bash
swag setup --auto --base-url http://127.0.0.1:8000/v1
```

`--base-url` does not fall through to a cloud menu. If that server is down,
or every sized model is under 7B, setup stops with an error.

### Free cloud plans

Use these only when nothing local answered and no key is set. A free plan
sends your prompts to that provider. That is not private, unlike the local
apps above. Free plans also rate-limit. The limit is on the provider's page
and it changes, so this doc does not copy a number.

Setup prints the page where you create a key, reads the key without echoing
it, and stores it in `$SWAG_HOME/provider-keys.env` with mode `0600`. You can
instead export the variable yourself. The value is not written to
`config.toml` and is not printed. If the variable is already set, setup uses
it and does not ask.

| Provider | Environment variable | Default model | Key | Limits |
| --- | --- | --- | --- | --- |
| Google Gemini (AI Studio) | `GEMINI_API_KEY` | `gemini-2.5-flash` | [AI Studio](https://aistudio.google.com/apikey) | [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| Groq | `GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` | [console keys](https://console.groq.com/keys) | [rate limits](https://console.groq.com/docs/rate-limits) |
| OpenRouter free router | `OPENROUTER_API_KEY` | `openrouter/free` | [keys](https://openrouter.ai/keys) | [limits](https://openrouter.ai/docs/api/reference/limits) |
| Cerebras | `CEREBRAS_API_KEY` | `cerebras/gpt-oss-120b` | [cloud console](https://cloud.cerebras.ai) | [models](https://inference-docs.cerebras.ai/models/overview) |
| Mistral | `MISTRAL_API_KEY` | `mistral/mistral-small-latest` | [API keys](https://console.mistral.ai/api-keys/) | [free mode](https://docs.mistral.ai/getting-started/quickstarts/studio/activate-and-generate-api-key) |

Gemini's client reads `GEMINI_API_KEY`, not `GOOGLE_API_KEY`. The live Gemini
model list is [Gemini models](https://ai.google.dev/gemini-api/docs/models).
OpenRouter's `:free` variant is documented at
[free model variants](https://openrouter.ai/docs/guides/routing/model-variants/free);
`openrouter/free` is their
[free router](https://openrouter.ai/docs/guides/routing/routers/free-router).
Groq and Cerebras model strings go through LiteLLM
([Groq](https://docs.litellm.ai/docs/providers/groq),
[Cerebras](https://docs.litellm.ai/docs/providers/cerebras)).
Mistral's LiteLLM ids are on
[Mistral](https://docs.litellm.ai/docs/providers/mistral).

GitHub Models was retired on 2026-07-30. The playground and inference API are
gone, so setup does not ask for a GitHub token. See
[GitHub Models](https://docs.github.com/en/github-models).

`--dry-run` prints the decision and writes nothing. A non-interactive run
(no terminal, `--yes` with no local model to pull, or `swag run` on a fresh
config) never waits for a key.

## Package layout

This is the models and memory slice of Swag Bot. The shared contracts stay in
`src/swag_bot/interfaces.py`. This package does not import `core`, `plugins`,
`safety`, or `mcp`.

## LLM clients

`get_llm_client(config)` in `swag_bot.models` returns an `LLMClient`.
Pass a `Settings` object, or omit it to load `$SWAG_HOME/config.toml`.

| `model.provider` | Client | Notes |
| --- | --- | --- |
| `ollama` (default) | `OllamaClient` | Local HTTP API. No key. Works offline. |
| `openai` | `LiteLLMClient` | `OPENAI_API_KEY` |
| `anthropic` | `LiteLLMClient` | `ANTHROPIC_API_KEY` |
| `gemini` | `LiteLLMClient` | `GEMINI_API_KEY` |
| `openrouter` | `LiteLLMClient` | `OPENROUTER_API_KEY` |
| `litellm` | `LiteLLMClient` | Model string is passed through. LiteLLM picks the key for that prefix. |

Ollama's base URL is `settings.model.api_base` when set, otherwise
`OLLAMA_HOST`, otherwise `http://127.0.0.1:11434`. The default model is
`llama3.2`.

LiteLLM is optional. The extra in `pyproject.toml` is named `models` (it
installs the `litellm` package):

```bash
python -m pip install -e ".[models]"
```

CI does not install it. Tests inject a completion function and never open a
socket. Keys are read from the environment at request time. They are not
fields on `Settings`, they are not in `repr`, and error text replaces a known
key value with `$ENV_VAR` before it is shown.

Both clients implement `StreamingLLMClient`. `stream` yields provider deltas
as they arrive. A model that rejects native tools is retried with streaming
still on, plus a system message that asks for a JSON tool call.

### Tool calls

Provider tool calls are normalized to `ToolCall`. Arguments may arrive as a
JSON string or a dict; callers always see a dict.

When native tools fail (or the model writes the call as text), the client
reads a JSON object of this shape:

```json
{"tool_calls": [{"name": "TOOL_NAME", "arguments": {}}]}
```

Fenced ` ```json ` blocks are accepted. A name that is not in the tool list
is ignored, so an ordinary JSON answer is not treated as a tool call.

### CLI

```bash
swag model list
swag model test
swag model test "Reply with the single word: ok"
swag model set ollama/llama3.2
swag model set openai/gpt-4o-mini
swag model set openrouter/anthropic/claude-3.5-sonnet
```

`list` prints the active `provider/model`, each cloud key as `set` or
`unset` (never the value), and local Ollama model names when `GET /api/tags`
answers. `set` writes `config.toml`. It does not write secrets. `test` sends
one short prompt.

### `build_llm_client`

`build_llm_client(settings)` is the factory `swag run` calls. It returns the
same client as `get_llm_client(settings)`. `swag model` keeps calling
`get_llm_client`.

### Small-model harness

`model.harness` is `auto` by default. On a real Ollama or LiteLLM client,
`swag run` probes the model once and caches the profile at
`$SWAG_HOME/harness/capability.json`. `swag model probe` and
`swag doctor --probe` do the same. `--force` ignores the cache.

The probe checks three things: a JSON object with keys `ok` and `n`, one
`echo_token` tool call, and the context length from Ollama `/api/show` when
that endpoint answers. It does not include a filled-in sample the model can
copy.

| Profile | When | What changes |
| --- | --- | --- |
| `tiny` | About 4B parameters or smaller, or a failed JSON or tool probe | Short prompts, no sample ids, at most 3 steps, one tool per turn, repeated writes blocked, JSON schema where supported, deterministic check that a file-and-run step actually ran |
| `standard` | A mid-size model that passed the probe | JSON schema where supported. Prompts and tool lists stay as they are |
| `frontier` | About 30B or a known frontier name, and a passing probe | JSON schema, and up to 8 tool rounds |
| `off` | Set `model.harness` | No probe, no scaffold, client timeout stays 120 seconds unless `model.timeout` is set |

Ollama's client timeout is 120 seconds, which is short for a 7B or larger
model on CPU. While the harness is on and `model.timeout` is unset, local
models use 300 seconds under 7B and 600 seconds at 7B and above. The probe
itself gives up after 20 seconds so a stuck model does not block the run,
and a timeout is not cached as a failed profile.

Optional escalation, after the active model has used its attempts:

```toml
[model]
harness = "auto"
timeout = 300

[model.fallback]
provider = "ollama"
model = "qwen2.5:7b"

[model.budget]
max_escalations = 1
max_extra_seconds = 180
max_cost_usd = 0
```

A local fallback costs $0, so `max_cost_usd = 0` still allows it. A cloud
fallback needs a budget above the estimated call (about $0.01 to $0.03).
The estimate also has to fit in `max_extra_seconds`.

## Memory

`get_memory_store(config)` in `swag_bot.memory` returns a `MemoryStore`.

| `memory.backend` | Store | Where |
| --- | --- | --- |
| `memory` (default) or `sqlite` | `SQLiteMemoryStore` | `~/.swag/memory.db`, or `memory.path` |
| `json` | `JsonFileMemoryStore` | `~/.swag/memory.json`, or `memory.path` |
| `agentmemory` | `AgentMemoryStore` | External server. Optional. |

A relative `memory.path` is resolved under `SWAG_HOME`. An absolute path is
kept. The default backend does not use the network.

SQLite stores `id`, `content`, metadata JSON, a tags column, and
`created_at`. Search uses FTS5 (`bm25`, best first, newer first on a tie)
and a case-insensitive substring pass over content, tags, and metadata so a
partial word still matches. An empty query returns nothing. `get` returns
None when the id is missing. `delete` returns True only if the row existed.
Tags come from metadata `tags` (a list or comma-separated string) or `tag`.

The JSON store is the file-backed match for the in-memory fake: substring
over content and metadata values, newest first. It is what the CLI tests use.

### agentmemory

[agentmemory](https://github.com/rohitg00/agentmemory) runs as its own
process. This adapter speaks HTTP and does not import the MCP SDK or
`swag_bot.mcp`.

- URL: `memory.path` when it is `http://` or `https://`, else
  `AGENTMEMORY_URL`, else `http://127.0.0.1:3111`.
- Transport: `AGENTMEMORY_TRANSPORT` is `rest` or `mcp`. If it is unset, a
  URL that ends in `/mcp` uses MCP and anything else uses REST.
- Secret: `AGENTMEMORY_SECRET` is sent as `Authorization: Bearer ...` and is
  redacted from errors. It is not stored in config.

REST calls `POST /agentmemory/remember`, `POST /agentmemory/smart-search`,
`GET /agentmemory/memories/{id}`, `POST /agentmemory/forget`, and
`GET /agentmemory/memories`. MCP posts JSON-RPC `tools/call` for
`memory_save`, `memory_smart_search`, `memory_recall`, and
`memory_governance_delete`.

### CLI

```bash
swag memory add "ship the release" --tag release
swag memory search release
swag memory list
swag memory forget <id>
```

`build_memory_store(settings)` is the factory `swag run` calls. It returns the
same store as `get_memory_store(settings)`. `swag memory` keeps calling
`get_memory_store`.
