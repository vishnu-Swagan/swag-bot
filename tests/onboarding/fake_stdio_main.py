"""Stdio MCP server used by the approval test.

Not collected by pytest. Patches the model client, then runs the real
``swag serve-mcp`` path so stdout stays the protocol channel.
"""

from __future__ import annotations

import os
import sys


def _responses(mode: str) -> list[object]:
    from swag_bot.interfaces import ChatResponse, Message, ToolCall
    from tests.core.support import plan_json, verdict

    plan = plan_json(
        [
            {
                "id": "write",
                "title": "Write hello",
                "instruction": "Write hello.txt",
                "success_criteria": "hello.txt contains hello",
            }
        ]
    )
    tool = ChatResponse(
        message=Message.assistant(
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="write_file",
                    arguments={"path": "hello.txt", "content": "hello"},
                )
            ]
        )
    )
    if mode == "allow":
        return [
            plan,
            tool,
            "wrote hello.txt",
            verdict(True, "file contains hello"),
            "Wrote hello.txt.",
        ]
    return [
        plan,
        tool,
        "denied",
        verdict(False, "not written", replan=False),
        tool,
        "denied",
        verdict(False, "not written", replan=False),
        "Blocked.",
    ]


def main() -> None:
    """Serve MCP on stdio with a scripted model and no terminal prompter."""
    mode = os.environ.get("SWAG_STDIO_FIXTURE", "deny")
    from tests.fakes import FakeLLMClient

    llm = FakeLLMClient(_responses(mode))

    import swag_bot.core.cli as core_cli
    from swag_bot.safety.prompter import RichApprovalPrompter

    def scripted_client(settings: object) -> FakeLLMClient:
        del settings
        return llm

    def terminal_prompter_used(self: RichApprovalPrompter, action: object) -> bool:
        del self, action
        sys.stderr.write("TERMINAL_PROMPTER\n")
        raise RuntimeError("terminal prompter used on the MCP channel")

    core_cli.build_llm_client = scripted_client  # type: ignore[assignment]
    RichApprovalPrompter.prompt = terminal_prompter_used  # type: ignore[method-assign]

    sys.argv = ["swag", "serve-mcp"]
    from swag_bot.cli import main as swag_main

    swag_main()


if __name__ == "__main__":
    main()
