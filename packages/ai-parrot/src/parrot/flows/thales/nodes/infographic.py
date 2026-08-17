"""InfographicNode — executive summary + decks -> infographic (FEAT-425 Module 3).

Calls ``InfographicToolkit.render_template`` (FEAT-308 pattern — works for
ANY agent, no pandas REPL required). Failures degrade gracefully: logged
and the node returns ``None`` rather than raising, since ``infographic`` is
``Optional`` on ``ThalesResult`` (spec G7) and must never abort the run.
"""

from __future__ import annotations

from typing import Any, Optional, Set

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.thales.nodes.registry import register_thales_node


@register_thales_node("thales.infographic")
class InfographicNode(Node):
    """Fan-in: executive summary + decks -> ``InfographicRenderResult`` (or ``None``).

    Args:
        node_id: Unique identifier within the graph.
        toolkit: An ``InfographicToolkit`` instance (injected — already
            configured with its templates; never constructed here).
        template_name: Name of a template already registered on ``toolkit``
            (e.g. the FEAT-308 ``crew_report`` route).
        title: Optional artifact title (defaults per the toolkit).
        exec_summary_node_id: node_id whose ``deps`` value is the executive
            summary string (``ExecSummaryNode``'s output).
        dependencies: Set of node_ids that must complete first — expected
            to be the exec-summary node plus every angle's ``DeckBuilderNode``.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    toolkit: Any
    template_name: str = "crew_report"
    title: Optional[str] = None
    exec_summary_node_id: str = "exec_summary"
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
    ) -> Optional[Any]:
        """Render the summary infographic, degrading to ``None`` on failure.

        Args:
            ctx: The current flow execution context (unused directly).
            deps: Mapping with the exec-summary string (keyed by
                ``exec_summary_node_id``) plus every deck's JSON output.

        Returns:
            The toolkit's ``InfographicRenderResult``, or ``None`` when
            rendering failed (logged, never raised).
        """
        try:
            executive_summary = deps.get(self.exec_summary_node_id, "")
            decks_payload = [
                raw for node_id, raw in deps.items()
                if node_id != self.exec_summary_node_id
            ]
            data = {
                "executive_summary": executive_summary,
                "decks": decks_payload,
            }
            return await self.toolkit.render_template(
                self.template_name, data=data, title=self.title,
            )
        except Exception as exc:  # noqa: BLE001 - graceful degrade contract (FEAT-308)
            self.logger.warning(
                "InfographicNode %s degraded (toolkit failure): %s", self.node_id, exc,
            )
            return None
