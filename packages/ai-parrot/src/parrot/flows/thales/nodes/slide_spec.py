"""SlideSpecNode — ResearchDeck -> SlideSpec (FEAT-425 Module 3).

LLM structured output only — never HTML (spec G4; deterministic rendering
is Module 4). Chart payloads are filtered post-hoc so they only ever
reference ``Finding.numeric_series`` actually present in the deck; no
invented numbers survive even if the LLM hallucinates a chart.
"""

from __future__ import annotations

from typing import Any, Optional, Set

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.thales.models import ResearchDeck, SlideSpec
from parrot.flows.thales.nodes.registry import register_thales_node


def _extract_slide_spec(message: Any) -> SlideSpec:
    """Extract the ``SlideSpec`` from a client response.

    ``AbstractClient.ask(..., structured_output=SlideSpec)`` populates
    ``AIMessage.structured_output`` (or, for some client paths, ``.data``).
    """
    for attr in ("structured_output", "data"):
        candidate = getattr(message, attr, None)
        if isinstance(candidate, SlideSpec):
            return candidate
        if isinstance(candidate, dict):
            return SlideSpec.model_validate(candidate)
    raise ValueError("Client response did not contain a structured SlideSpec.")


def _build_prompt(deck: ResearchDeck) -> str:
    """Build the slide-spec prompt from one research deck."""
    findings_text = "\n".join(f"- {finding.text}" for finding in deck.findings)
    return (
        f"Angle: {deck.angle.title}\n"
        f"Question: {deck.angle.question}\n\n"
        f"Findings:\n{findings_text}\n\n"
        "Fill a slide spec (deck_ref, layout, headline, bullets, and "
        "optionally charts/tables/quotes). Only propose a chart when the "
        "findings above actually contain numeric series data — never "
        "invent numbers."
    )


@register_thales_node("thales.slide_spec")
class SlideSpecNode(Node):
    """``ResearchDeck`` -> ``SlideSpec`` (LLM structured output).

    Args:
        node_id: Unique identifier within the graph.
        client: An ``AbstractClient``-like object exposing an async
            ``ask(prompt, *, structured_output=...)`` method. Injected via
            ``node_factories`` (TASK-2231).
        dependencies: Set of node_ids that must complete first — expects
            exactly one upstream dependency: the angle's ``DeckBuilderNode``.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    client: Any
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
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
        """Fill a ``SlideSpec`` for the deck found in ``deps``.

        Args:
            ctx: The current flow execution context.
            deps: Mapping with exactly one entry: the upstream
                ``DeckBuilderNode``'s JSON-encoded ``ResearchDeck``.

        Returns:
            The ``SlideSpec`` as JSON, with ``charts`` filtered to only
            those the deck's findings can actually back.
        """
        deck = self._deck_from_deps(deps)
        message = await self.client.ask(_build_prompt(deck), structured_output=SlideSpec)
        spec = _extract_slide_spec(message)

        has_numeric_series = any(finding.numeric_series for finding in deck.findings)
        if not has_numeric_series and spec.charts:
            spec = spec.model_copy(update={"charts": []})

        return spec.model_dump_json()

    @staticmethod
    def _deck_from_deps(deps: DependencyResults) -> ResearchDeck:
        """Parse the single upstream ``DeckBuilderNode`` output."""
        if not deps:
            raise ValueError("SlideSpecNode requires exactly one upstream deck dependency.")
        raw = next(iter(deps.values()))
        return ResearchDeck.model_validate_json(raw)
