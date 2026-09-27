# core

**Owner:** the core agent (plan-do-verify).

**Edit only:** `src/swag_bot/core/` and `tests/core/`.

Read `docs/ARCHITECTURE.md` before touching a shared file. `interfaces.py` changes stay additive.

## What goes here

The loop behind `swag run "<goal>"`.

- Turn a goal into a `TaskPlan` of `Step`s (`PlanDoVerifyLoop` in `loop.py`).
- Do each step with the injected `LLMClient`, `ToolRegistry`, `Sandbox`, and `MemoryStore`.
- Verify the step, then set its status to `done` or `failed`.
- Ask `PermissionPolicy` and `ApprovalPrompter` before side effects. The safety package writes the `ActionLogEntry`; call into its public API rather than writing the log from here.

`loop.py` takes collaborators in its constructor so this package does not import `models`, `memory`, `safety`, `mcp`, or `plugins`. Wire them in `cli.py` when you replace the stub:

```python
from swag_bot.config import load_settings
from swag_bot.core.loop import PlanDoVerifyLoop
from swag_bot.memory import build_memory_store
from swag_bot.models import build_llm_client
from swag_bot.safety import build_permission_policy, build_prompter, build_sandbox

settings = load_settings()
loop = PlanDoVerifyLoop(
    llm=build_llm_client(settings),
    sandbox=build_sandbox(settings),
    memory=build_memory_store(settings),
    policy=build_permission_policy(settings),
    prompter=build_prompter(settings),
)
plan = loop.run(goal)
```

Until a factory is real it raises `NotImplementedYet`. Catch that if you want `swag run` to work before the other packages land, and use `tests/fakes.py` in tests.

## CLI

`cli.py` defines the `run` command. The root app flattens it to `swag run`. Keep that name. Replace `unimplemented("swag run")`.

## Status

Stub. `swag run` exits 2.
