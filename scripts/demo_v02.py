"""Scripted 0.2 run: failing check, handoff, offline replay, gated promotion.

Uses the in-process client so the demo does not call a network model.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swag_bot.config import SkillLearningMode
from swag_bot.core.cli import execute_goal
from swag_bot.interfaces import AutonomyLevel, ChatResponse, Message, ToolCall
from swag_bot.learning.adapters import StubEvidenceSource, StubRunReplayer
from swag_bot.learning.errors import SkillLearningError
from swag_bot.learning.protocols import CompletedRun, ReplayRequest
from swag_bot.learning.runtime import BundleRunReplayer, LedgerEvidenceSource
from swag_bot.learning.service import learn_from_run, promote_candidate
from tests.core.support import plan_json, verdict
from tests.fakes import FakeLLMClient


def _write(path: str, content: str) -> ChatResponse:
    return ChatResponse(
        message=Message.assistant(
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="write_file",
                    arguments={"path": path, "content": content},
                )
            ]
        )
    )


def _section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="swag-v02-"))
    home = root / "home"
    home.mkdir()
    os.environ["SWAG_HOME"] = str(home)
    out = root / "failed-run"
    llm = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "write",
                        "title": "Write hello",
                        "instruction": "Write hello.txt",
                        "success_criteria": "hello.txt contains hello",
                        "checks": [
                            {
                                "id": "has-hello",
                                "kind": "file_contains",
                                "path": "hello.txt",
                                "contains": "hello",
                            }
                        ],
                    },
                    {
                        "id": "prove",
                        "title": "Prove the missing line",
                        "instruction": "Confirm hello.txt contains the missing token",
                        "success_criteria": "the missing token is present",
                        "depends_on": ["write"],
                        "checks": [
                            {
                                "id": "has-token",
                                "kind": "file_contains",
                                "path": "hello.txt",
                                "contains": "missing-token",
                            }
                        ],
                    },
                ]
            ),
            _write("hello.txt", "hello"),
            "wrote hello.txt",
            verdict(True, "hello is in the file"),
            "The token is not there.",
        ]
    )
    failed = execute_goal(
        "Write hello.txt and then prove a missing token",
        output_dir=out,
        client=llm,
        autonomy=AutonomyLevel.AUTO,
        memory_mode="off",
        record=True,
        max_attempts=1,
        concurrency=1,
    )
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    _section("1. Failing check marked failed, with evidence")
    print(f"exit_code={failed.exit_code}")
    for step in plan["steps"]:
        print(f"[{step['status']}] {step['id']} {step['title']}")
    for line in (out / "run.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("record") != "check":
            continue
        check = row["check"]
        state = "passed" if check["passed"] else "failed"
        ids = ", ".join(check["evidence_ids"]) or "(none)"
        print(f"check {check['check_id']} {state}: {check['detail']}")
        print(f"  evidence: {ids}")

    _section("2. Step handoff cites evidence ids")
    for turn in llm.messages:
        for message in turn:
            text = message.content or ""
            if "evidence:" not in text:
                continue
            for handoff_line in text.splitlines():
                stripped = handoff_line.strip()
                if handoff_line.startswith("- write:") or stripped.startswith("evidence:"):
                    print(handoff_line)

    good_out = root / "good-run"
    good_llm = FakeLLMClient(
        [
            plan_json(
                [
                    {
                        "id": "write",
                        "title": "Write hello",
                        "instruction": "Write hello.txt",
                        "success_criteria": "hello.txt contains hello",
                    }
                ]
            ),
            _write("hello.txt", "hello"),
            "wrote hello.txt",
            verdict(True, "file contains hello"),
            "Wrote hello.txt.",
        ]
    )
    good = execute_goal(
        "Write hello.txt",
        output_dir=good_out,
        client=good_llm,
        autonomy=AutonomyLevel.AUTO,
        memory_mode="off",
        record=True,
        max_attempts=1,
        concurrency=1,
    )
    good_plan = json.loads((good_out / "plan.json").read_text(encoding="utf-8"))
    run_id = str(good_plan["id"])
    _section("3. Recorded bundle replayed offline")
    print(f"recorded exit_code={good.exit_code} run_id={run_id}")
    replayed = BundleRunReplayer(home).replay(
        ReplayRequest(
            run_id=run_id,
            goal="Write hello.txt",
            skill_name="write-hello",
            varied=False,
        )
    )
    print(f"replay outcome={replayed.outcome.value}")
    print(f"replay detail={replayed.detail}")
    print((home / "replays" / f"{run_id}.json").read_text(encoding="utf-8").rstrip())

    _section("4. Skill candidate promoted only after evidence and replay pass")
    learned = learn_from_run(
        CompletedRun.model_validate(good_plan),
        home=home,
        mode=SkillLearningMode.REVIEW,
        evidence=StubEvidenceSource(),
        replayer=StubRunReplayer(),
    )
    assert learned.candidate is not None
    print(f"quarantined {learned.candidate.id}: {learned.reason}")
    candidate_id = learned.candidate.id
    for label, evidence, replayer in (
        ("evidence stub", StubEvidenceSource(), BundleRunReplayer(home)),
        ("replay stub", LedgerEvidenceSource(home), StubRunReplayer()),
        ("ledger + bundle replay", LedgerEvidenceSource(home), BundleRunReplayer(home)),
    ):
        try:
            promoted = promote_candidate(
                candidate_id,
                home=home,
                evidence=evidence,
                replayer=replayer,
            )
        except SkillLearningError as exc:
            print(f"{label}: NOT promoted: {exc}")
            continue
        print(f"{label}: promoted {promoted.candidate.skill_name if promoted.candidate else ''}")
        print(f"  location: {promoted.active_path}")


if __name__ == "__main__":
    main()
