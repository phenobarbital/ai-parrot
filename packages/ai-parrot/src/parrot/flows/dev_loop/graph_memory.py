"""DevLoopGraphMemory — opt-in GraphIndex facade for dev_loop (FEAT-377 G2).

The single integration surface between the agent-fleet flow (``dev_loop``)
and the permanent-memory knowledge graph (``parrot.knowledge.graphindex``).
Node code (TASK-1915) stays thin: it calls this facade, never the
graphindex components directly.

Disabled by default (``DEV_LOOP_GRAPH_MEMORY_PATH`` unset →
:meth:`DevLoopGraphMemory.from_config` returns ``None``) — every seam
this facade backs (research context injection, run write-back, finding
grounding) degrades to a no-op when disabled, so zero-config dev_loop
runs are byte-identical to before this feature landed.

**v1 scope decision (2026-07-26)**: write-back targets the SQLite plane
only — the same components :func:`build_graph_memory_toolkit` composes
internally, built here directly (WITHOUT the ``parrot_tools`` agent
toolkit — this facade needs the graphindex components, not the tool
surface). Arango deployments will project these memory kinds later
through the Module 2 ontology (TASK-1909); no dual publish in v1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Union

from parrot.knowledge.graphindex import (
    CommitReceipt,
    ContextBuildConfig,
    EdgeKind,
    GraphContextBuilder,
    GraphPublisher,
    GraphUpdate,
    GroundingEvaluator,
    NodeKind,
    Provenance,
    SQLitePersistence,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.factory import (
    DEFAULT_DIMENSION,
    HashingGraphEmbedder,
    make_stub_tenant_context,
)
from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

from parrot.flows.dev_loop.models import QAReport, WorkBrief

logger = logging.getLogger(__name__)

# Default token budget for research-context injection (Seam 2, TASK-1915).
_DEFAULT_CONTEXT_TOKENS = 4000


class DevLoopGraphMemory:
    """Facade wiring GraphIndex into dev_loop nodes (opt-in).

    Construct via :meth:`from_config` — never directly — so every caller
    shares the same "disabled unless configured" contract.

    Args:
        publisher: The :class:`GraphPublisher` write path.
        context_builder: The :class:`GraphContextBuilder` read path
            (research-context injection).
        grounding_evaluator: The :class:`GroundingEvaluator` used to
            ground code-review findings.
        agent_id: Stable identity stamped onto every write
            (``GraphUpdate.agent_id``).
    """

    def __init__(
        self,
        *,
        publisher: GraphPublisher,
        context_builder: GraphContextBuilder,
        grounding_evaluator: GroundingEvaluator,
        agent_id: str,
    ) -> None:
        self._publisher = publisher
        self._context_builder = context_builder
        self._grounding_evaluator = grounding_evaluator
        self._agent_id = agent_id
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    async def from_config(
        cls,
        *,
        tenant_id: str = "default",
        agent_id: str = "dev-loop",
        dimension: int = DEFAULT_DIMENSION,
    ) -> Optional["DevLoopGraphMemory"]:
        """Build the facade from ``conf.DEV_LOOP_GRAPH_MEMORY_PATH``.

        Mirrors ``build_graph_memory_toolkit``'s load -> assemble -> embed
        sequence (``factory.py:203-236``), but stops short of building a
        ``GraphIndexToolkit`` — this facade needs the raw graphindex
        components (persistence, publisher, retriever, context builder,
        grounding evaluator), not the agent tool surface, and must not
        depend on the sibling ``ai-parrot-tools`` distribution.

        Args:
            tenant_id: Tenant identifier inside the SQLite plane.
            agent_id: Stable agent identity stamped onto writes.
            dimension: Embedding dimension for the offline hashing embedder.

        Returns:
            A ready :class:`DevLoopGraphMemory`, or ``None`` when
            ``DEV_LOOP_GRAPH_MEMORY_PATH`` is unset (the disabled default).
        """
        from parrot import conf  # noqa: PLC0415 - defer conf import to call time

        db_dir = (getattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", "") or "").strip()
        if not db_dir:
            return None

        ctx = make_stub_tenant_context(tenant_id)
        persistence = SQLitePersistence(Path(db_dir))
        publisher = GraphPublisher(persistence, ctx)

        nodes, edges = await persistence.load_graph(ctx)

        assembler = GraphAssembler(tenant_id=tenant_id)
        for node in nodes:
            assembler.add_node(node)
        for edge in edges:
            assembler.add_edge(edge)

        embedder = HashingGraphEmbedder(dimension=dimension)
        if nodes:
            await embedder.embed_nodes(nodes)

        retriever = GraphExpandedRetriever(
            graph=assembler.graph, nodes=nodes, embedder=embedder
        )
        context_builder = GraphContextBuilder(retriever)
        grounding_evaluator = GroundingEvaluator(retriever)

        logger.info(
            "DevLoopGraphMemory.from_config: opened %r (tenant=%s, %d nodes, %d edges)",
            db_dir, tenant_id, len(nodes), len(edges),
        )
        return cls(
            publisher=publisher,
            context_builder=context_builder,
            grounding_evaluator=grounding_evaluator,
            agent_id=agent_id,
        )

    # ------------------------------------------------------------------
    # Seam 2 — research context injection
    # ------------------------------------------------------------------

    async def build_research_context(
        self, brief: Union[WorkBrief, str]
    ) -> Optional[str]:
        """Build budget-capped, citable context for a research dispatch.

        Args:
            brief: The work brief driving this run's research dispatch, or
                a bare query string. Feature-mode intake
                (:class:`~parrot.flows.dev_loop.models.FeatureBrief`) has
                no ``summary`` field to retrieve on, so ``PlannerNode``
                passes a query string derived from its SDD document — the
                same shape ``DevLoopWikiSearch.build_research_context``
                already accepts.

        Returns:
            Markdown context text ready for prompt injection, or ``None``
            when nothing relevant was found (or on any internal error —
            context injection is best-effort, never fatal).
        """
        query = brief if isinstance(brief, str) else brief.summary
        try:
            context = await self._context_builder.build(
                query,
                ContextBuildConfig(max_tokens=_DEFAULT_CONTEXT_TOKENS),
            )
        except Exception as exc:  # noqa: BLE001 - best-effort context
            self.logger.warning(
                "DevLoopGraphMemory.build_research_context failed: %s", exc
            )
            return None
        # `context.text` always carries a header template, even with zero
        # matches — `node_ids` is the real "found nothing" signal (same
        # check GraphMemoryMixin._build_graph_context uses).
        if not context.node_ids:
            return None
        return context.text

    # ------------------------------------------------------------------
    # Seam 3 — run write-back
    # ------------------------------------------------------------------

    async def publish_run_outcome(
        self,
        run_id: str,
        report: Optional[QAReport],
        outcome: str,
        summary: str,
    ) -> Optional[CommitReceipt]:
        """Publish one audited ``GraphUpdate`` recording this run's outcome.

        Constructs a ``RUN`` node, one ``CLAIM`` node per verified
        (``passed``) criterion in ``report.criterion_results``, and the
        edges connecting them: ``PRODUCED`` (run -> claim, work lineage),
        ``ABOUT`` (claim -> run, "this claim concerns this run") and
        ``SUPPORTED_BY`` (claim -> run, the run IS the claim's evidence —
        no separate entity/evidence source is available at this
        signature's narrower scope; TASK-1915's node-level callers pass
        whatever ``summary`` they have).

        Degrade-never-fail: any exception (closed store, disk full, ...)
        is caught, logged as a warning, and degrades to ``None`` — a
        graph write must never fail the flow node that triggered it.

        Args:
            run_id: The flow run id.
            report: The final ``QAReport``, or ``None`` for a run that
                never reached QA (e.g. a hard node error).
            outcome: Terminal outcome label (e.g. ``"closed"``,
                ``"escalated"``).
            summary: Human-readable run summary (becomes the RUN node's
                title/summary).

        Returns:
            The :class:`CommitReceipt` on success, or ``None`` on any
            failure.
        """
        try:
            run_node_id = f"run:{run_id}"
            run_node = UniversalNode(
                node_id=run_node_id,
                kind=NodeKind.RUN,
                title=f"dev-loop run {run_id} ({outcome})",
                source_uri=f"dev_loop://run/{run_id}",
                summary=summary,
                domain_tags={"outcome": outcome},
                provenance=Provenance.ASSERTED,
            )
            nodes: List[UniversalNode] = [run_node]
            edges: List[UniversalEdge] = []

            verified = [
                c for c in (report.criterion_results if report else []) if c.passed
            ]
            for criterion in verified:
                claim_node_id = f"claim:{run_id}:{criterion.name}"
                nodes.append(
                    UniversalNode(
                        node_id=claim_node_id,
                        kind=NodeKind.CLAIM,
                        title=criterion.name,
                        source_uri=f"dev_loop://run/{run_id}/criterion/{criterion.name}",
                        summary=(
                            f"{criterion.kind} criterion verified "
                            f"(exit={criterion.exit_code})"
                        ),
                        provenance=Provenance.ASSERTED,
                    )
                )
                edges.append(
                    UniversalEdge(
                        source_id=run_node_id,
                        target_id=claim_node_id,
                        kind=EdgeKind.PRODUCED,
                        provenance=Provenance.ASSERTED,
                    )
                )
                edges.append(
                    UniversalEdge(
                        source_id=claim_node_id,
                        target_id=run_node_id,
                        kind=EdgeKind.ABOUT,
                        provenance=Provenance.ASSERTED,
                    )
                )
                edges.append(
                    UniversalEdge(
                        source_id=claim_node_id,
                        target_id=run_node_id,
                        kind=EdgeKind.SUPPORTED_BY,
                        provenance=Provenance.ASSERTED,
                    )
                )

            update = GraphUpdate(
                nodes=nodes,
                edges=edges,
                agent_id=self._agent_id,
                run_id=run_id,
                asserted_by=f"dev_loop:{outcome}",
            )
            return await self._publisher.publish(update)
        except Exception as exc:  # noqa: BLE001 - degrade-never-fail (persist_warning convention)
            self.logger.warning(
                "DevLoopGraphMemory.publish_run_outcome failed for run %s: %s",
                run_id, exc,
            )
            return None

    # ------------------------------------------------------------------
    # Seam 4 — grounded code-review findings
    # ------------------------------------------------------------------

    async def ground_findings(self, findings: List[str]) -> List[str]:
        """Filter findings to those the graph can ground as ``"grounded"``.

        Each finding string is evaluated independently via
        ``GroundingEvaluator.ground_claim``; findings the evaluator
        returns ``decision == "revise"`` for are dropped (callers may
        demote them to advisory notes instead of gate-failing — TASK-1915).
        A finding whose evaluation itself raises is KEPT (fail toward
        keeping human-relevant signal, never silently drops a finding on
        an infra error) and logged as a warning.

        Args:
            findings: Raw finding strings from a code-review verdict.

        Returns:
            The subset of ``findings`` grounded by the graph, in order.
        """
        kept: List[str] = []
        for finding in findings:
            try:
                result = await self._grounding_evaluator.ground_claim(finding)
            except Exception as exc:  # noqa: BLE001 - never drop on infra error
                self.logger.warning(
                    "DevLoopGraphMemory.ground_findings: evaluation failed for "
                    "%r, keeping finding: %s",
                    finding, exc,
                )
                kept.append(finding)
                continue
            if result.decision == "grounded":
                kept.append(finding)
        return kept


__all__ = ["DevLoopGraphMemory"]
