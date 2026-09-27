"""``execute_goal`` keeps the extension hooks optional."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swag_bot.core.cli import execute_goal
from swag_bot.extension.policy import CatalogRiskPolicy
from swag_bot.interfaces import ActionRequest, AutonomyLevel
from tests.fakes import FakeLLMClient


def _plan() -> str:
    return json.dumps(
        {
            "steps": [
                {
                    "id": "look",
                    "title": "Look",
                    "instruction": "Look at the page",
                    "success_criteria": "the observation mentions the page",
                    "depends_on": [],
                }
            ]
        }
    )


def _verdict() -> str:
    return json.dumps({"passed": True, "reason": "saw the page", "replan": False})


def test_hooks_reach_the_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    llm = FakeLLMClient([_plan(), "the page says hello", _verdict(), "Read the page."])
    monkeypatch.setattr("swag_bot.core.cli.build_llm_client", lambda settings: llm)
    seen: dict[str, object] = {}

    class Prompter:
        def prompt(self, action: ActionRequest) -> bool:
            seen["prompted"] = True
            return False

    def prepare(registry: object) -> None:
        seen["tools"] = [tool.name for tool in registry.list_tools()]  # type: ignore[attr-defined]

    def wrap(policy: object) -> CatalogRiskPolicy:
        seen["policy"] = policy
        return CatalogRiskPolicy(policy)  # type: ignore[arg-type]

    result = execute_goal(
        "Read the attached page",
        output_dir=tmp_path / "out",
        autonomy=AutonomyLevel.ASK_RISKY,
        prompter=Prompter(),
        prepare_tools=prepare,  # type: ignore[arg-type]
        policy_wrapper=wrap,  # type: ignore[arg-type]
        context_prefix="UNTRUSTED PAGE marker",
        max_steps=2,
        concurrency=1,
    )
    assert result.exit_code == 0
    assert "Read the page." in result.summary
    assert seen.get("prompted") is None
    assert "read_file" in seen["tools"]  # type: ignore[operator]
    assert seen["policy"] is not None
    planner_text = "\n".join(message.content or "" for turn in llm.messages for message in turn)
    assert "UNTRUSTED PAGE marker" in planner_text
