"""Plan-do-verify loop.

The core agent replaces ``PlanDoVerifyLoop.run``. Dependencies are injected
so this module does not import models, safety, plugins, mcp, or memory.
"""

from __future__ import annotations

from swag_bot.errors import NotImplementedYet
from swag_bot.interfaces import (
    ApprovalPrompter,
    LLMClient,
    MemoryStore,
    PermissionPolicy,
    Sandbox,
    TaskPlan,
    ToolRegistry,
)


class PlanDoVerifyLoop:
    """Turn a goal into a ``TaskPlan``, run each step, and verify it.

    Stub. ``run`` raises ``NotImplementedYet``. The constructor only stores
    the collaborators the real loop will use.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        sandbox: Sandbox,
        memory: MemoryStore,
        policy: PermissionPolicy,
        prompter: ApprovalPrompter,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.memory = memory
        self.policy = policy
        self.prompter = prompter
        self.tools = tools

    def run(self, goal: str) -> TaskPlan:
        """Plan, do, and verify ``goal``. Not implemented yet."""
        raise NotImplementedYet("PlanDoVerifyLoop.run")


__all__ = ["PlanDoVerifyLoop"]
