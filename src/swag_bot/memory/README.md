# memory

**Owner:** the models and memory agent. You also own `src/swag_bot/models/` and `tests/models/`.

**Edit only:** `src/swag_bot/memory/`, `src/swag_bot/models/`, `tests/memory/`, and `tests/models/`.

Read `docs/ARCHITECTURE.md` before touching a shared file. `interfaces.py` changes stay additive.

## What goes here

`MemoryStore` implementations selected by `settings.memory.backend`.

- `memory` (the default) is process-local. `tests/fakes.py` `InMemoryMemoryStore` is the behavior to match: `add`, `search`, `get`, `delete`. Search is case-insensitive over content and metadata values, newest match first. An empty query returns nothing.
- A later file-backed backend (sqlite or json) uses `settings.memory.path`. If that path is relative, resolve it under `SWAG_HOME`.
- `build_memory_store(settings)` in `__init__.py` is what `swag run` will call. Keep the name.
- The default backend does not make network calls.

## CLI

`swag memory search`. Add subcommands on this Typer app.

## Status

Stub. The command exits 2.
