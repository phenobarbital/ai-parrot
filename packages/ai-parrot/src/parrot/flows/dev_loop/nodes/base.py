"""DevLoopNode — shared base for the dev-loop flow nodes.

Adapts the dev-loop nodes to the FEAT-163 ``AgentsFlow`` scheduler
contract:

- carries the ``dependencies`` / ``successors`` / ``fsm`` fields the
  event-driven scheduler expects (the FSM is auto-created per node and
  re-created per run by ``AgentsFlow._materialize_nodes``);
- normalizes the execute signature to ``execute(ctx, deps, **kwargs)``
  where ``ctx`` is a :class:`FlowContext`. For unit-test ergonomics a
  plain dict is also accepted and treated as the shared state itself.

Cross-node payloads (``bug_brief``, ``research_output``,
``development_output``, ``qa_report``, ``run_id``, …) travel in
``FlowContext.shared_data``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Union

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node


class DevLoopNode(Node):
    """Base node for the dev-loop flow (FEAT-129 / FEAT-132).

    Subclasses implement ``execute(ctx, deps, **kwargs)`` and use
    :meth:`shared_state` to read/write cross-node payloads.

    Args:
        node_id: Unique identifier within the flow graph.
        dependencies: Upstream node_ids (optional — ``AgentsFlow`` derives
            them from the edge list in explicit-edge mode).
        successors: Downstream node_ids (optional, same reason).
        fsm: Per-run task FSM; auto-created when ``None``.
    """

    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create the FSM; initialise the base logger."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier used by the flow router."""
        return self.node_id

    # ── Context helpers ──────────────────────────────────────────────────

    @staticmethod
    def shared_state(ctx: Union[FlowContext, Dict[str, Any]]) -> Dict[str, Any]:
        """Return the mutable cross-node state dict for *ctx*.

        Args:
            ctx: The flow execution context. A :class:`FlowContext` yields
                its ``shared_data``; a plain dict (unit tests) is returned
                as-is.

        Returns:
            The shared mutable mapping.

        Raises:
            TypeError: When *ctx* is neither a FlowContext nor a dict.
        """
        if isinstance(ctx, FlowContext):
            return ctx.shared_data
        if isinstance(ctx, dict):
            return ctx
        raise TypeError(
            f"dev-loop nodes expect FlowContext or dict, got {type(ctx)!r}"
        )

    @staticmethod
    def initial_prompt(ctx: Union[FlowContext, Dict[str, Any]]) -> str:
        """Return the run's initial task/prompt string.

        Args:
            ctx: The flow execution context.

        Returns:
            ``FlowContext.initial_task`` (or the dict's ``"initial_task"``
            key), empty string when absent.
        """
        if isinstance(ctx, FlowContext):
            return ctx.initial_task or ""
        if isinstance(ctx, dict):
            return str(ctx.get("initial_task") or "")
        return ""


__all__ = ["DevLoopNode"]
