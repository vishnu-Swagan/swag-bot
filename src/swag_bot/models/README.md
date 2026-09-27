# models

**Owner:** the models and memory agent. You also own `src/swag_bot/memory/` and `tests/memory/`.

**Edit only:** `src/swag_bot/models/`, `src/swag_bot/memory/`, `tests/models/`, and `tests/memory/`.

Read `docs/ARCHITECTURE.md` before touching a shared file. `interfaces.py` changes stay additive.

## What goes here

`LLMClient` implementations selected by `settings.model.provider` and `settings.model.model`.

- `ollama` is the default. Talk to `OLLAMA_HOST` (default `http://127.0.0.1:11434`) or `settings.model.api_base` when it is set.
- `litellm` covers multi-provider routing. It stays an optional extra (`pip install -e ".[models]"`).
- Direct bring-your-own-key clients for OpenAI and Anthropic read `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the environment. Never read a key from `config.toml`, never log one, never put one in an `ActionRequest`.
- Implement `StreamingLLMClient` only when the provider streams. Otherwise raise `NotImplementedError` from any stream method you add, and do not pretend to stream.
- `build_llm_client(settings)` in `__init__.py` is what `swag run` will call. Keep the name.

Parse provider tool-call arguments into the `ToolCall.arguments` dict (the model accepts a JSON string). Map provider messages onto `Message` / `Role`.

## CLI

`swag model list`. Add subcommands on this Typer app.

## Status

Stub. The command exits 2.
