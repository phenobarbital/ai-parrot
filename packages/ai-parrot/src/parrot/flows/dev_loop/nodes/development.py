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

from typing import Any, Dict, Optional, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    DevelopmentOutput,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node


@register_dev_loop_node("dev_loop.development")
class DevelopmentNode(DevLoopNode):
    """Third node — dispatches the implementation phase to ``sdd-worker``."""

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        name: str = "development",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> DevelopmentOutput:
        """Dispatch ``sdd-worker`` inside the upstream worktree.

        Args:
            ctx: Flow context whose shared state must contain ``"run_id"``
                and ``"research_output"`` (a :class:`ResearchOutput`
                produced by ``ResearchNode``).
            deps: Dependency results (unused — payloads travel in the
                shared state).
            **kwargs: Extra execution context (ignored).

        Returns:
            The validated :class:`DevelopmentOutput`.
        """
        shared = self.shared_state(ctx)
        research: ResearchOutput = shared["research_output"]

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
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
        )
        shared["development_output"] = dev_out
        return dev_out


__all__ = ["DevelopmentNode"]
