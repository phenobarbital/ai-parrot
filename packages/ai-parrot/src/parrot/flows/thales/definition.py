"""Flow assembly for the "Thales" research flow (FEAT-425 Module 5).

**Deviation from the original spec §7 wiring plan — verified during
TASK-2231 implementation, two rounds of user-approved corrections:**

1. The spec originally called for a pure ``build_thales_definition(angles,
   config) -> FlowDefinition`` handed to
   ``AgentsFlow.from_definition(..., node_factories=...)``. Verified against
   `dev`: ``from_definition()`` requires **every** node type (including
   ``node_factories``-injected ones) to already be registered in the global
   ``NODE_REGISTRY`` — ``node_factories`` only overrides *construction* of
   an already-registered type, never registration itself. Per the first
   user decision ("Option B"), this module instead builds the flow
   **programmatically** — ``AgentsFlow(name=..., checkpoint=True)`` +
   ``add_node()``/``add_edge()`` (this is also exactly "explicit-edge
   mode", which natively provides the OR-join + skip-propagation semantics
   ``DeckBuilderNode`` needs).

2. Running the assembled flow end-to-end then surfaced a SECOND, deeper
   requirement: ``checkpoint=True`` *itself* calls ``AgentsFlow.
   to_definition()`` as a fail-fast export check (FEAT-399,
   ``_ensure_checkpointer``) — **regardless of assembly mode** — and that
   export requires every node's class to resolve via ``NODE_REGISTRY``
   too. So "programmatic mode" alone does not avoid registration when
   checkpointing is wanted; per the second user decision ("Option C"),
   every Thales node type IS registered, via the same idempotent
   ``@register_node`` pattern ``parrot.flows.dev_loop`` already uses
   (``nodes/registry.py``) — see the updated spec §7.

   ``to_definition()`` export also rejects live Python callables as edge
   predicates ("only CEL expression strings round-trip") — so the
   ``deck -> slide_spec`` "don't render a dropped deck" gate is a CEL
   string (``_DECK_NOT_DROPPED_CEL``), not a Python function, mirroring
   ``parrot.flows.dev_loop.definition``'s own CEL-string predicates.

``build_thales_nodes_and_edges`` stays as side-effect-free as this allows:
given a bag of already-constructed live dependencies (``ThalesNodeDeps``),
it returns the full node/edge lists with no I/O of its own (agent/client
construction is cheap object instantiation, not a network call — the
network calls happen later, inside each node's ``execute()``).
``assemble_thales_flow`` is the thin wrapper that actually calls
``add_node``/``add_edge`` on a fresh ``AgentsFlow`` instance.

Two research-execution node types this module introduces (``_ResearchNode``
for the three v1 sources per angle, ``_SlideRenderNode`` for TASK-2228's
deterministic renderer) were never assigned their own task file — the
spec's Component Diagram names them (``research[i][web/deep/arxiv]`` and
``slide_render[i]``) but no file in TASK-2227/2229/2230's Files-to-Create
lists covers building them as ``Node`` subclasses. Both are private,
underscore-prefixed, and live here (this task's own file) rather than
touching any already-committed task's files (beyond the registration
correction in point 2 above).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple, Optional, Set

from pydantic import Field

from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import EndNode, Node, StartNode
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.flows.thales.factories import (
    arxiv_to_findings,
    build_arxiv_agent,
    build_deep_research_caller,
    build_web_agent,
    deep_research_to_findings,
    extract_groundedness_report,
    websearch_to_findings,
)
from parrot.flows.thales.models import ResearchAngle, SlideSpec, ThalesConfig
from parrot.flows.thales.nodes import (
    BibliographyNode,
    DeckBuilderNode,
    ExecSummaryNode,
    FinalDocumentNode,
    InfographicNode,
    SlideSpecNode,
)
from parrot.flows.thales.nodes.deck_builder import DROPPED_DECK_SENTINEL
from parrot.flows.thales.nodes.registry import register_thales_node
from parrot.flows.thales.rendering import render_slide

#: Maps ThalesConfig.sources entries to the short internal labels used as
#: node-id/DeckBuilderNode.sources segments (distinct from the config's own
#: machine-readable source names).
_SOURCE_LABELS: dict[str, str] = {
    "web": "web",
    "deep_research": "deep",
    "arxiv": "arxiv",
}


class EdgeSpec(NamedTuple):
    """One (from, to, condition, predicate) edge, mirroring `AgentsFlow.add_edge`.

    ``predicate`` is a CEL expression **string**, never a Python callable —
    ``AgentsFlow.to_definition()`` (required by ``checkpoint=True``'s
    fail-fast export check) only round-trips CEL strings, mirroring
    ``parrot.flows.dev_loop.definition``'s own CEL-string predicates.
    """

    from_: str
    to: str
    condition: str = "always"
    predicate: Optional[str] = None


@dataclass
class ThalesNodeDeps:
    """Live dependencies closed over by the assembled flow's nodes.

    Attributes:
        client: Shared ``AbstractClient``-like object (exposes async
            ``ask(prompt, *, structured_output=...)``) used by
            ``SlideSpecNode`` and the deep-research research nodes.
        store: An ``ArtifactStore`` instance for ``FinalDocumentNode``.
        toolkit: An ``InfographicToolkit`` instance for ``InfographicNode``.
        user_id: Owning user identifier for persistence.
        agent_id: Agent identifier for persistence.
        session_id: Session identifier for persistence.
        accessed_date: ISO date this run's sources were retrieved (injected
            once per run — never derived deep inside a node, for testability).
        title: Final document title.
        output_dir: Optional filesystem directory `FinalDocumentNode` ALSO
            mirrors the final document (+ PDF) into, independent of
            `store` (code-review fix: the final document was previously
            only reachable via `ArtifactStore`).
    """

    client: Any
    store: Any
    toolkit: Any
    user_id: str
    agent_id: str
    session_id: str
    accessed_date: str
    title: str = "Thales Research Report"
    output_dir: Optional[Any] = None


#: CEL predicate: only proceed to slide_spec when the deck was NOT dropped.
#: ``result`` (the deck_builder node's raw JSON-string output) is bound as
#: a CEL string by the engine's ``CELPredicateEvaluator`` — ``.contains()``
#: is the CEL "strings" extension function (verified against ``celpy``).
#: A plain Python callable predicate cannot be used here: it would make
#: ``AgentsFlow.to_definition()`` raise ``FlowNotExportableError``, which
#: ``checkpoint=True`` calls unconditionally as a fail-fast check.
_DECK_NOT_DROPPED_CEL = f'!result.contains("{DROPPED_DECK_SENTINEL}")'


@register_thales_node("thales.research")
class _ResearchNode(Node):
    """One research call (web / deep / arxiv) for one angle.

    Normalizes its source's raw output into a JSON-encoded ``list[Finding]``
    via the TASK-2227 factories normalizers. Exceptions propagate to the
    scheduler unhandled — a failed source simply never appears in
    ``DeckBuilderNode``'s ``deps`` (OR-join degrade, spec §7).

    Args:
        node_id: Unique identifier within the graph.
        source: One of ``"web"``, ``"deep"``, ``"arxiv"``.
        angle: The research angle this node investigates.
        accessed_date: ISO date of retrieval (injected, never computed
            inside ``execute()``).
        config: The run's ``ThalesConfig`` (paragraph cap, per-node timeout).
        agent: The built agent for ``"web"``/``"arxiv"`` sources.
        deep_caller: The async callable from
            :func:`~parrot.flows.thales.factories.build_deep_research_caller`
            for the ``"deep"`` source.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    source: str
    angle: ResearchAngle
    accessed_date: str
    config: ThalesConfig
    agent: Any = None
    deep_caller: Any = None
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

    async def execute(self, ctx: Any, deps: Any, **kwargs: Any) -> str:
        """Run this source's research call and return JSON-encoded findings."""
        coro = self._run_source()
        if self.config.per_node_timeout:
            return await asyncio.wait_for(coro, timeout=self.config.per_node_timeout)
        return await coro

    async def _run_source(self) -> str:
        if self.source == "arxiv":
            message = await self.agent.ask(self.angle.question)
            tool_call = next(
                (tc for tc in getattr(message, "tool_calls", []) if tc.name == "arxiv_search"),
                None,
            )
            execute_result = (
                tool_call.result
                if tool_call is not None and isinstance(tool_call.result, dict)
                else {"papers": []}
            )
            groundedness = extract_groundedness_report(message)
            findings = arxiv_to_findings(
                execute_result,
                accessed_date=self.accessed_date,
                config=self.config,
                groundedness_report=groundedness,
            )
        elif self.source == "deep":
            message = await self.deep_caller(self.angle.question)
            findings = deep_research_to_findings(
                message, accessed_date=self.accessed_date, config=self.config,
            )
        else:  # "web"
            message = await self.agent.ask(self.angle.question)
            findings = websearch_to_findings(
                message, accessed_date=self.accessed_date, config=self.config,
            )
        return json.dumps([finding.model_dump(mode="json") for finding in findings])


@register_thales_node("thales.slide_render")
class _SlideRenderNode(Node):
    """Deterministic rendering of one angle's ``SlideSpec`` into slide HTML.

    Thin wiring node over TASK-2228's pure :func:`render_slide` — no LLM
    call, no business logic of its own.

    Args:
        node_id: Unique identifier within the graph.
        dependencies: Set of node_ids that must complete first — expected
            to be exactly one upstream ``SlideSpecNode``.
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

    async def execute(self, ctx: Any, deps: Any, **kwargs: Any) -> str:
        """Render the upstream ``SlideSpec`` into deterministic HTML."""
        if not deps:
            return ""
        raw = next(iter(deps.values()))
        spec = SlideSpec.model_validate_json(raw)
        return await render_slide(spec)


def build_thales_nodes_and_edges(
    angles: list[ResearchAngle],
    config: ThalesConfig,
    deps: ThalesNodeDeps,
) -> tuple[list[Node], list[EdgeSpec]]:
    """Build every ``Node`` instance + edge spec for one Thales run.

    Side-effect-free beyond object construction (no network I/O — every
    network call happens later, inside a node's ``execute()``). Exhaustively
    testable with varying angle counts / enabled sources.

    Args:
        angles: All research angles for this run (``len >= config.num_decks``
            is the caller's/``PlannerNode``'s responsibility, not enforced
            here).
        config: The run's ``ThalesConfig``.
        deps: Live dependencies closed over by the constructed nodes.

    Returns:
        ``(nodes, edges)`` — every ``Node`` instance and every
        ``EdgeSpec`` needed to wire them via
        ``AgentsFlow.add_node``/``add_edge``.
    """
    nodes: list[Node] = [StartNode(node_id="start"), EndNode(node_id="end")]
    edges: list[EdgeSpec] = []

    enabled_labels = [
        _SOURCE_LABELS[source] for source in config.sources if source in _SOURCE_LABELS
    ]

    deep_caller = (
        build_deep_research_caller(config) if "deep" in enabled_labels else None
    )

    deck_ids: list[str] = []
    slide_render_ids: list[str] = []

    for angle in angles:
        research_ids: list[str] = []
        for label in enabled_labels:
            node_id = f"research-{label}-{angle.angle_id}"
            if label == "web":
                node = _ResearchNode(
                    node_id=node_id, source=label, angle=angle,
                    accessed_date=deps.accessed_date, config=config,
                    agent=build_web_agent(angle, config),
                )
            elif label == "arxiv":
                node = _ResearchNode(
                    node_id=node_id, source=label, angle=angle,
                    accessed_date=deps.accessed_date, config=config,
                    agent=build_arxiv_agent(angle, config),
                )
            else:  # "deep"
                node = _ResearchNode(
                    node_id=node_id, source=label, angle=angle,
                    accessed_date=deps.accessed_date, config=config,
                    deep_caller=deep_caller,
                )
            nodes.append(node)
            research_ids.append(node_id)
            edges.append(EdgeSpec(from_="start", to=node_id))

        deck_id = f"deck-{angle.angle_id}"
        nodes.append(DeckBuilderNode(node_id=deck_id, angle=angle, sources=research_ids))
        deck_ids.append(deck_id)
        for research_id in research_ids:
            # Both conditions so deck_builder always dispatches (OR-join):
            # whichever fires, the join never blocks on this source.
            edges.append(EdgeSpec(from_=research_id, to=deck_id, condition="on_success"))
            edges.append(EdgeSpec(from_=research_id, to=deck_id, condition="on_error"))

        slide_spec_id = f"slide-spec-{angle.angle_id}"
        nodes.append(SlideSpecNode(node_id=slide_spec_id, client=deps.client))
        edges.append(EdgeSpec(from_=deck_id, to=slide_spec_id, predicate=_DECK_NOT_DROPPED_CEL))

        slide_render_id = f"slide-render-{angle.angle_id}"
        nodes.append(_SlideRenderNode(node_id=slide_render_id))
        slide_render_ids.append(slide_render_id)
        edges.append(EdgeSpec(from_=slide_spec_id, to=slide_render_id))

    nodes.append(BibliographyNode(node_id="bibliography"))
    for deck_id in deck_ids:
        edges.append(EdgeSpec(from_=deck_id, to="bibliography"))

    nodes.append(ExecSummaryNode(node_id="exec_summary"))
    for deck_id in deck_ids:
        edges.append(EdgeSpec(from_=deck_id, to="exec_summary"))

    nodes.append(
        FinalDocumentNode(
            node_id="final_document",
            store=deps.store,
            user_id=deps.user_id,
            agent_id=deps.agent_id,
            session_id=deps.session_id,
            slide_node_ids=slide_render_ids,
            bibliography_node_id="bibliography",
            title=deps.title,
            output_dir=deps.output_dir,
        )
    )
    for slide_render_id in slide_render_ids:
        edges.append(EdgeSpec(from_=slide_render_id, to="final_document"))
    edges.append(EdgeSpec(from_="bibliography", to="final_document"))

    nodes.append(
        InfographicNode(
            node_id="infographic",
            toolkit=deps.toolkit,
            exec_summary_node_id="exec_summary",
        )
    )
    edges.append(EdgeSpec(from_="exec_summary", to="infographic"))
    for deck_id in deck_ids:
        edges.append(EdgeSpec(from_=deck_id, to="infographic"))

    edges.append(EdgeSpec(from_="final_document", to="end"))
    edges.append(EdgeSpec(from_="infographic", to="end"))

    return nodes, edges


def assemble_thales_flow(
    angles: list[ResearchAngle],
    config: ThalesConfig,
    deps: ThalesNodeDeps,
    *,
    flow_id: Optional[str] = None,
    on_node_event: Optional[Callable[[str, str, dict], Any]] = None,
) -> AgentsFlow:
    """Build a ready-to-run ``AgentsFlow`` for one Thales run (phase 2).

    Programmatic assembly (explicit-edge mode) — see this module's
    docstring for why ``FlowDefinition``/``from_definition`` is not used.

    Args:
        angles: All research angles for this run (from phase 1's planner).
        config: The run's ``ThalesConfig``.
        deps: Live dependencies closed over by the constructed nodes.
        flow_id: Stable flow id so ``checkpoint=True`` resume works
            (FEAT-399).
        on_node_event: Optional node-event listener forwarded to
            ``AgentsFlow``'s constructor.

    Returns:
        A configured ``AgentsFlow`` instance ready for ``run_flow(ctx)``.
    """
    nodes, edges = build_thales_nodes_and_edges(angles, config, deps)

    flow = AgentsFlow(
        name="thales",
        checkpoint=True,
        flow_id=flow_id,
        on_node_event=on_node_event,
    )
    for node in nodes:
        flow.add_node(node)
    for edge in edges:
        flow.add_edge(
            edge.from_, edge.to, condition=edge.condition, predicate=edge.predicate,
        )
    return flow
