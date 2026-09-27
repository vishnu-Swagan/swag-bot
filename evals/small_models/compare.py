"""Compare scaffold choices, and optionally probe a live Ollama model.

Offline (no daemon)::

    python evals/small_models/compare.py

Live probe (Ollama must already be running and the model must be pulled)::

    python evals/small_models/compare.py --live qwen2.5:3b

This does not claim benchmark scores. It prints the probe the harness
actually ran.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from swag_bot.harness.probe import choose_scaffold
from swag_bot.harness.sizing import parameter_billions, request_timeout_seconds

_ROOT = Path(__file__).resolve().parents[2]
_TASKS = Path(__file__).resolve().parent / "tasks.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show small-model harness decisions.")
    parser.add_argument(
        "--live",
        metavar="MODEL",
        help="Probe this Ollama model and print the cached profile.",
    )
    args = parser.parse_args()
    tasks = json.loads(_TASKS.read_text(encoding="utf-8"))
    print(f"tasks: {len(tasks)} in {_TASKS.relative_to(_ROOT)}")
    print("name heuristic (probe scores assumed perfect, context unknown):")
    for name in ("qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b", "llama3.2", "gpt-4o"):
        scaffold = choose_scaffold(
            model=name,
            json_adherence=1.0,
            tool_call_reliability=1.0,
            context_tokens=None,
        )
        timeout = request_timeout_seconds("ollama", name, None)
        size = parameter_billions(name)
        print(f"  {name}: size={size} scaffold={scaffold} ollama_timeout={timeout}")
    if not args.live:
        print("no live model requested")
        return 0
    from swag_bot.config import ModelSettings, Settings
    from swag_bot.harness.probe import profile_model, render_report
    from swag_bot.models.factory import get_llm_client

    settings = Settings(model=ModelSettings(provider="ollama", model=args.live, harness="auto"))
    client = get_llm_client(settings)
    report = profile_model(
        client=client,
        provider="ollama",
        model=args.live,
        api_base=None,
        force=True,
    )
    print(render_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
