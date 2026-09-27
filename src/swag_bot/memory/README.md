# memory

**Owner:** the models and memory agent. You also own `src/swag_bot/models/` and `tests/models/`.

**Edit only:** `src/swag_bot/memory/`, `src/swag_bot/models/`, `tests/memory/`, and `tests/models/`.

Read `docs/ARCHITECTURE.md` and `docs/MODELS.md` before touching a shared file. `interfaces.py` changes stay additive. This slice did not change `interfaces.py`.

## What is here

`get_memory_store(config)` returns a `MemoryStore`:

- `memory` (the config default) and `sqlite` open SQLite at `~/.swag/memory.db` (or `settings.memory.path`). FTS5, tags, and timestamps. No network.
- `json` is a JSON file with the same substring search as `InMemoryMemoryStore` in `tests/fakes.py`.
- `agentmemory` talks to an external [agentmemory](https://github.com/rohitg00/agentmemory) server over REST or MCP HTTP. Optional. The URL and `AGENTMEMORY_SECRET` come from config/env, never a committed secret.

`build_memory_store` still raises `NotImplementedYet` so `tests/test_fakes.py` stays green. Call `get_memory_store`.

## CLI

`swag memory add`, `swag memory search`, `swag memory list`, and `swag memory forget`.
