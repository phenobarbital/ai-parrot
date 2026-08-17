"""ExecSummaryNode — synthesis over all decks (FEAT-425 Module 3).

Wraps the flow plane's ``synthesize_results`` util (the same one
``SynthesisNode`` uses, ``bots/flows/flow/flow.py:1963``) — mirrors that
node's minimal ``FlowResult``-duck-type-from-deps pattern exactly.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.storage.synthesis import synthesize_results
from parrot.bots.flows.core.types import DependencyResults


class _PartialResult:
    """Minimal FlowResult duck-type for `synthesize_results` (mirrors SynthesisNode)."""

    def __init__(self, responses: Dict[str, Any]) -> None:
        self.responses = responses
        self.summary = ""


class ExecSummaryNode(Node):
    """Fan-in over all decks -> one executive-summary string (LLM synthesis).

    Args:
        node_id: Unique identifier within the graph.
        dependencies: Set of node_ids that must complete first — expected
            to be every angle's ``DeckBuilderNode`` (or slide/deck text).
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook (initialises ``self.logger``)."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> str:
        """Run LLM synthesis over the accumulated deck/deps text.

        Args:
            ctx: The current flow execution context. Must have
                ``ctx.synthesis_client`` set (see ``synthesize_results``).
            deps: Mapping of completed dependency node_id -> result string.

        Returns:
            The synthesized executive-summary string.
        """
        partial = _PartialResult(responses=dict(deps))
        return await synthesize_results(ctx, partial)  # type: ignore[arg-type]
