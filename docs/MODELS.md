# Models and memory

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
`get_llm_client`. No fields were added to `interfaces.py`.

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
