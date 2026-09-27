# models

**Owner:** the models and memory agent. You also own `src/swag_bot/memory/` and `tests/memory/`.

**Edit only:** `src/swag_bot/models/`, `src/swag_bot/memory/`, `tests/models/`, and `tests/memory/`.

Read `docs/ARCHITECTURE.md` and `docs/MODELS.md` before touching a shared file. `interfaces.py` changes stay additive. This slice did not change `interfaces.py`.

## What is here

`get_llm_client(config)` returns an `LLMClient`:

- `ollama` (the default) talks to `OLLAMA_HOST` or `settings.model.api_base`. No key.
- `openai`, `anthropic`, `gemini`, `openrouter`, and `litellm` go through LiteLLM. Install it with `pip install -e ".[models]"`. Keys stay in the environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`).

Both clients stream when the provider streams, and both fall back to JSON-in-text tool calls when native tools are unavailable. Tool arguments are always a dict.

`build_llm_client` still raises `NotImplementedYet` so `tests/test_fakes.py` stays green. Call `get_llm_client`.

## CLI

`swag model list`, `swag model test`, and `swag model set <provider/model>`.
