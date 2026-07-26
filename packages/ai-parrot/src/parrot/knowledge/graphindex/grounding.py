"""Grounding evaluator — check claims against graph evidence.

Implements the paper's grounding layer: instead of a free-form critique,
a claim is checked for supporting *paths* in the knowledge graph. When
support exists, the result cites the exact edges (stable ids); when it
does not, the result is a structured revise instruction listing the
missing evidence — actionable feedback an agent can act on
(add the missing relation, find a source, or weaken the claim).

Example revise contract::

    {
      "decision": "revise",
      "claim": "Vendor X supplied the component in Incident Y",
      "reason": "No supported path between 'Vendor X' and 'Incident Y'",
      "required_evidence": [
        "A path connecting 'Vendor X' and 'Incident Y' (e.g. a"
        " supported_by/references relation)"
      ]
    }
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.graphindex.context_builder import GraphContextBuilder
from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
from parrot.knowledge.graphindex.schema import stable_edge_id

logger = logging.getLogger(__name__)


class GroundingJudgement(BaseModel):
    """Structured output of the optional LLM semantic check.

    Args:
        supported: Whether the cited paths actually support the claim
            semantically (connectivity alone can be coincidental).
        reason: One-sentence justification.
        confidence: Judgement confidence in [0, 1].
    """

    supported: bool
    reason: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class GroundingResult(BaseModel):
    """Outcome of grounding one claim against the graph.

    Args:
        decision: ``"grounded"`` when supporting paths exist (and the
            optional LLM judgement agrees); ``"revise"`` otherwise.
        claim: The claim that was checked.
        reason: Human-readable explanation of the decision.
        entities: Resolved ``node_id`` of each claim entity found in the
            graph.
        unresolved_entities: Claim terms that could not be resolved
            (only populated when resolution found nothing for them).
        supported_paths: One list of stable edge ids per supporting
            path (citable evidence).
        contradictions: Stable edge ids of ``contradicts`` relations
            touching the claim's entities.
        required_evidence: When revising — the specific missing
            entities/relations that would ground the claim.
        confidence: Support confidence in [0, 1].
    """

    decision: Literal["grounded", "revise"]
    claim: str
    reason: str
    entities: list[str] = Field(default_factory=list)
    unresolved_entities: list[str] = Field(default_factory=list)
    supported_paths: list[list[str]] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


_JUDGEMENT_PROMPT = """Claim: {claim}

Evidence paths found in a knowledge graph (each line is one relation):
{paths}

Question: do these relations, taken together, actually SUPPORT the claim
semantically? Connectivity alone is not support — the relation kinds and
directions must be consistent with what the claim states.
"""


class GroundingEvaluator:
    """Check claims for edge-level support in a knowledge graph.

    Args:
        retriever: A :class:`GraphExpandedRetriever` over the graph
            (supplies the graph, node models, and entity surface forms).
        client: Optional ``AbstractClient``; when present, a structured
            LLM judgement confirms that found paths semantically support
            the claim (path existence alone can be coincidental).
        max_hops: Maximum path length considered supporting evidence.
    """

    def __init__(
        self,
        retriever: GraphExpandedRetriever,
        client: Optional[Any] = None,
        max_hops: int = 2,
    ) -> None:
        self.retriever = retriever
        self.client = client
        self.max_hops = max_hops
        self._builder = GraphContextBuilder(retriever)
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Graph helpers
    # ------------------------------------------------------------------

    def _adjacency(self) -> dict[str, list[tuple[str, str, str, str]]]:
        """Undirected adjacency: node_id → [(other, src, dst, kind)]."""
        adj: dict[str, list[tuple[str, str, str, str]]] = {}
        graph = self.retriever.graph
        for idx in graph.node_indices():
            payload = graph[idx]
            if not isinstance(payload, dict):
                continue
            for _s, _t, edge in graph.out_edges(idx):
                if not isinstance(edge, dict):
                    continue
                src = edge.get("source_id")
                dst = edge.get("target_id")
                kind = edge.get("kind")
                if not src or not dst or not kind:
                    continue
                adj.setdefault(src, []).append((dst, src, dst, kind))
                adj.setdefault(dst, []).append((src, src, dst, kind))
        return adj

    def _find_path(
        self,
        adj: dict[str, list[tuple[str, str, str, str]]],
        start: str,
        goal: str,
    ) -> Optional[list[tuple[str, str, str]]]:
        """BFS for the shortest undirected path within ``max_hops``.

        ``contradicts`` edges never count as supporting evidence.

        Returns:
            List of ``(src, dst, kind)`` triples, or ``None``.
        """
        if start == goal:
            return []
        queue: deque[tuple[str, list[tuple[str, str, str]]]] = deque(
            [(start, [])]
        )
        visited = {start}
        while queue:
            current, path = queue.popleft()
            if len(path) >= self.max_hops:
                continue
            for other, src, dst, kind in adj.get(current, []):
                if kind == "contradicts":
                    continue
                if other in visited:
                    continue
                new_path = path + [(src, dst, kind)]
                if other == goal:
                    return new_path
                visited.add(other)
                queue.append((other, new_path))
        return None

    def _contradictions_touching(self, node_ids: set[str]) -> list[str]:
        """Stable edge ids of contradicts-edges incident on the entities."""
        found: list[str] = []
        graph = self.retriever.graph
        for idx in graph.node_indices():
            payload = graph[idx]
            if not isinstance(payload, dict):
                continue
            for _s, _t, edge in graph.out_edges(idx):
                if not isinstance(edge, dict):
                    continue
                if edge.get("kind") != "contradicts":
                    continue
                src, dst = edge.get("source_id"), edge.get("target_id")
                if src in node_ids or dst in node_ids:
                    found.append(stable_edge_id(src, dst, "contradicts"))
        return sorted(set(found))

    def _titles(self) -> dict[str, str]:
        return {n.node_id: n.title for n in self.retriever.nodes}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ground_claim(self, claim: str) -> GroundingResult:
        """Ground a claim against the graph.

        Args:
            claim: Natural-language claim to check.

        Returns:
            A :class:`GroundingResult` — grounded with cited edge paths,
            or a structured revise instruction.
        """
        from parrot.knowledge.graphindex.context_builder import (
            ContextBuildConfig,
        )

        entity_ids = await self._builder._resolve_entities(
            claim, ContextBuildConfig()
        )
        titles = self._titles()

        if len(entity_ids) < 2:
            resolved = [titles.get(e, e) for e in entity_ids]
            return GroundingResult(
                decision="revise",
                claim=claim,
                reason=(
                    "Fewer than two claim entities resolve to graph nodes"
                    f" (resolved: {resolved or 'none'}) — the graph cannot"
                    " evidence a relationship."
                ),
                entities=entity_ids,
                required_evidence=[
                    "Graph nodes for the entities the claim mentions"
                    " (file them via create_concept / remember, or check"
                    " the entity names)."
                ],
            )

        adj = self._adjacency()
        supported_paths: list[list[str]] = []
        missing_pairs: list[tuple[str, str]] = []
        # Check consecutive-pair connectivity (anchor entity to the rest).
        anchor = entity_ids[0]
        for other in entity_ids[1:]:
            path = self._find_path(adj, anchor, other)
            if path is None:
                missing_pairs.append((anchor, other))
            else:
                supported_paths.append(
                    [stable_edge_id(s, d, k) for s, d, k in path]
                )

        contradictions = self._contradictions_touching(set(entity_ids))

        if missing_pairs:
            required = [
                f"A source-backed path connecting {titles.get(a, a)!r} and"
                f" {titles.get(b, b)!r} (within {self.max_hops} hops)"
                for a, b in missing_pairs
            ]
            return GroundingResult(
                decision="revise",
                claim=claim,
                reason=(
                    "No supported path between "
                    + "; ".join(
                        f"{titles.get(a, a)!r} and {titles.get(b, b)!r}"
                        for a, b in missing_pairs
                    )
                ),
                entities=entity_ids,
                supported_paths=supported_paths,
                contradictions=contradictions,
                required_evidence=required,
            )

        # Optional LLM semantic judgement over the found paths.
        confidence = 0.6 if self.client is None else 0.0
        reason = "Supporting paths found for every claim entity pair."
        if self.client is not None:
            try:
                serialized = "\n".join(
                    f"- path {i + 1}: {line}"
                    for i, line in enumerate(
                        self._serialize_paths(entity_ids, adj)
                    )
                )
                result = await self.client.invoke(
                    _JUDGEMENT_PROMPT.format(claim=claim, paths=serialized),
                    output_type=GroundingJudgement,
                    system_prompt=(
                        "You are a strict evidence judge for a knowledge"
                        " graph. Only mark supported=true when the relations"
                        " genuinely entail the claim."
                    ),
                )
                judgement = getattr(result, "output", result)
                if isinstance(judgement, dict):
                    judgement = GroundingJudgement(**judgement)
                if not judgement.supported:
                    return GroundingResult(
                        decision="revise",
                        claim=claim,
                        reason=f"Paths exist but do not support the claim:"
                        f" {judgement.reason}",
                        entities=entity_ids,
                        supported_paths=supported_paths,
                        contradictions=contradictions,
                        required_evidence=[
                            "Relations whose kinds/directions match what the"
                            " claim states (current paths are topologically"
                            " connected but semantically insufficient)."
                        ],
                        confidence=judgement.confidence,
                    )
                confidence = judgement.confidence
                reason = judgement.reason or reason
            except Exception as exc:  # noqa: BLE001 — judge is optional
                self.logger.warning("grounding judgement failed: %s", exc)
                confidence = 0.6

        if contradictions:
            reason += (
                f" NOTE: {len(contradictions)} contradicts-relation(s) touch"
                " these entities — review before relying on the claim."
            )

        return GroundingResult(
            decision="grounded",
            claim=claim,
            reason=reason,
            entities=entity_ids,
            supported_paths=supported_paths,
            contradictions=contradictions,
            confidence=confidence,
        )

    def _serialize_paths(
        self,
        entity_ids: list[str],
        adj: dict[str, list[tuple[str, str, str, str]]],
    ) -> list[str]:
        """Human-readable path lines for the LLM judge."""
        titles = self._titles()
        lines: list[str] = []
        anchor = entity_ids[0]
        for other in entity_ids[1:]:
            path = self._find_path(adj, anchor, other)
            if not path:
                continue
            hops = " ; ".join(
                f"{titles.get(s, s)} -{k}-> {titles.get(d, d)}"
                for s, d, k in path
            )
            lines.append(hops)
        return lines
