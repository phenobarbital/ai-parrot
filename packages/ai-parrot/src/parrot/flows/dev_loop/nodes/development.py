"""DevelopmentNode — sdd-worker dispatch.

Implements **Module 6**. A thin node that hands the worktree off to the
``sdd-worker`` subagent under ``permission_mode="acceptEdits"``. The
subagent reads the spec and implements all unblocked tasks in
dependency order, committing after each one.

The dispatcher's R4 cwd-safety check verifies that
``ResearchOutput.worktree_path`` lives under
``conf.WORKTREE_BASE_PATH``. This node trusts that check and does not
duplicate it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from parrot.bots.flow.node import Node
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    DevelopmentOutput,
    ResearchOutput,
)


class DevelopmentNode(Node):
    """Third node — dispatches the implementation phase to ``sdd-worker``."""

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        name: str = "development",
    ) -> None:
        super().__init__()
        self._name = name
        self._init_node(name)
        self._dispatcher = dispatcher
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return self._name

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self, prompt: str, ctx: Dict[str, Any]
    ) -> DevelopmentOutput:
        """Dispatch ``sdd-worker`` inside the upstream worktree.

        Args:
            prompt: Unused (the dispatcher builds its own prompt body).
            ctx: Must contain ``"run_id"`` and ``"research_output"``
                (a :class:`ResearchOutput` produced by ``ResearchNode``).

        Returns:
            The validated :class:`DevelopmentOutput`.
        """
        research: ResearchOutput = ctx["research_output"]

        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            permission_mode="acceptEdits",
            allowed_tools=[
                "Read",
                "Edit",
                "Write",
                "Bash",
                "Grep",
                "Glob",
            ],
            setting_sources=["project"],
        )

        dev_out: DevelopmentOutput = await self._dispatcher.dispatch(
            brief=research,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id=ctx["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
        )
        ctx["development_output"] = dev_out
        return dev_out


__all__ = ["DevelopmentNode"]
