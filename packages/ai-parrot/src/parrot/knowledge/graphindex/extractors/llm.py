"""LLM-typed knowledge extraction into the graph (schema-constrained).

Replaces a classical NER/relation pipeline with one structured-output
call: the Pydantic schema is the only "training data". Extracted
entities are deduplicated against the existing graph (exact, alias, and
fuzzy title matching), merges are additive and inspectable (canonical
nodes keep aliases + a merge rationale), and everything lands in ONE
audited, revertible commit attributed to the extracting agent/run.

The other extractors in this package are structural (tree-sitter, file
headings); this one turns free text — conversation notes, documents,
decisions — into typed nodes and edges.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.schema import (
    CommitReceipt,
    EdgeKind,
    GraphUpdate,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)

#: Fuzzy title-similarity threshold for entity deduplication.
_FUZZY_THRESHOLD = 0.88

_EXTRACTION_PROMPT = """Extract a typed knowledge graph from the text below.

Rules:
- entities: the distinct things the text is about (concepts, components,
  services, people, policies). Use short canonical names; put variant
  names in aliases. kind is one of: concept, document, symbol, skill.
- relations: subject-predicate-object links BETWEEN the entities you
  extracted (use the exact entity names as source/target). kind is one
  of: references, contains, defines, mentions, explains, extends.
- Give each entity a one-sentence summary grounded in the text.
- confidence in [0, 1]: how directly the text supports the item.
- Do NOT invent entities or relations not supported by the text.

Text:
---
{text}
---
"""


class ExtractedEntity(BaseModel):
    """A typed entity extracted from free text.

    Args:
        name: Short canonical name.
        kind: Node kind string (validated against ``NodeKind``; unknown
            kinds fall back to ``concept``).
        summary: One-sentence description grounded in the source text.
        aliases: Variant surface forms seen in the text.
        confidence: Extraction confidence in [0, 1].
    """

    name: str
    kind: str = "concept"
    summary: str = ""
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ExtractedRelation(BaseModel):
    """A typed relation between two extracted entities.

    Args:
        source: Name of the subject entity (must match an entity name).
        target: Name of the object entity.
        kind: Edge kind string (validated against ``EdgeKind``; unknown
            kinds fall back to ``references``).
        rationale: Short justification quoted/paraphrased from the text.
        confidence: Extraction confidence in [0, 1].
    """

    source: str
    target: str
    kind: str = "references"
    rationale: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ExtractedGraph(BaseModel):
    """The structured-output contract for one extraction call."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


class ExtractionPublishResult(BaseModel):
    """Outcome of :meth:`LLMGraphExtractor.extract_and_publish`.

    Args:
        receipt: The recorded commit.
        extracted: The raw LLM extraction.
        update: The deduplicated update that was committed (post-merge
            nodes and resolved edges) — callers can mirror it into an
            in-memory graph.
    """

    receipt: CommitReceipt
    extracted: ExtractedGraph
    update: GraphUpdate


def _mint_node_id(kind: str, title: str, summary: str) -> str:
    """Deterministic node id (same recipe as the toolkit's write tools)."""
    raw = f"{kind}::{title}::{summary}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


class LLMGraphExtractor:
    """Extract typed knowledge from text and publish it durably.

    Args:
        client: An ``AbstractClient`` (uses its provider-native
            structured output via ``invoke(output_type=...)``).
        publisher: Optional :class:`GraphPublisher`; required for
            :meth:`extract_and_publish`.
    """

    def __init__(
        self,
        client: Any,
        publisher: Optional[GraphPublisher] = None,
    ) -> None:
        self.client = client
        self.publisher = publisher
        self.logger = logging.getLogger(__name__)

    async def extract(self, text: str) -> ExtractedGraph:
        """Run the schema-constrained extraction call.

        Args:
            text: Free text to extract from.

        Returns:
            The parsed :class:`ExtractedGraph`.
        """
        result = await self.client.invoke(
            _EXTRACTION_PROMPT.format(text=text),
            output_type=ExtractedGraph,
            system_prompt=(
                "You are a precise knowledge-graph extraction engine. "
                "Return only what the text supports."
            ),
        )
        output = getattr(result, "output", result)
        if isinstance(output, ExtractedGraph):
            return output
        if isinstance(output, dict):
            return ExtractedGraph(**output)
        raise TypeError(
            f"extraction returned unsupported type {type(output).__name__}"
        )

    # ------------------------------------------------------------------
    # Dedup + publish
    # ------------------------------------------------------------------

    @staticmethod
    def _match_existing(
        entity: ExtractedEntity,
        existing: list[UniversalNode],
    ) -> Optional[UniversalNode]:
        """Find the canonical node an extracted entity refers to.

        Blocking order: exact title match (case-insensitive) → alias
        match → fuzzy title similarity above :data:`_FUZZY_THRESHOLD`.
        """
        name = entity.name.strip().lower()
        surfaces = {name} | {a.strip().lower() for a in entity.aliases if a}
        best: Optional[UniversalNode] = None
        best_ratio = 0.0
        for node in existing:
            title = node.title.strip().lower()
            node_aliases = {
                str(a).strip().lower()
                for a in (node.domain_tags.get("aliases") or [])
            }
            if title in surfaces or (node_aliases & surfaces):
                return node
            ratio = difflib.SequenceMatcher(None, name, title).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = node
        if best is not None and best_ratio >= _FUZZY_THRESHOLD:
            return best
        return None

    async def extract_and_publish(
        self,
        text: str,
        source_uri: str,
        agent_id: str = "agent",
        run_id: Optional[str] = None,
    ) -> tuple[CommitReceipt, ExtractedGraph]:
        """Extract, dedup against the existing graph, and commit.

        Matched entities are merged ADDITIVELY: the canonical node keeps
        its identity and gains the new surface forms in
        ``domain_tags['aliases']`` plus a ``merge_rationale`` entry — no
        node is ever destroyed by extraction, and the whole batch is one
        revertible commit.

        Args:
            text: Free text to extract from.
            source_uri: Citation URI for the extracted knowledge.
            agent_id: Agent identity for attribution.
            run_id: Optional run/session id for lineage.

        Returns:
            An :class:`ExtractionPublishResult` with the commit receipt,
            the raw extraction, and the committed update.

        Raises:
            RuntimeError: When no publisher is configured.
        """
        if self.publisher is None:
            raise RuntimeError(
                "extract_and_publish requires a GraphPublisher"
            )

        extracted = await self.extract(text)

        existing_nodes, _ = await self.publisher.persistence.load_graph(
            self.publisher.ctx
        )

        name_to_id: dict[str, str] = {}
        upserts: dict[str, UniversalNode] = {}
        for entity in extracted.entities:
            if not entity.name.strip():
                continue
            try:
                kind = NodeKind(entity.kind)
            except ValueError:
                kind = NodeKind.CONCEPT

            canonical = self._match_existing(entity, existing_nodes)
            if canonical is not None:
                # Additive alias merge on the canonical node.
                aliases = {
                    str(a) for a in (canonical.domain_tags.get("aliases") or [])
                }
                new_surfaces = {
                    s
                    for s in [entity.name, *entity.aliases]
                    if s and s.strip().lower() != canonical.title.strip().lower()
                }
                added = sorted(new_surfaces - aliases)
                if added:
                    canonical.domain_tags["aliases"] = sorted(aliases | new_surfaces)
                    rationales = list(
                        canonical.domain_tags.get("merge_rationale") or []
                    )
                    rationales.append(
                        f"aliases {added} from extraction of {source_uri}"
                    )
                    canonical.domain_tags["merge_rationale"] = rationales
                    upserts[canonical.node_id] = canonical
                name_to_id[entity.name.strip().lower()] = canonical.node_id
                for alias in entity.aliases:
                    name_to_id.setdefault(alias.strip().lower(), canonical.node_id)
                continue

            node_id = _mint_node_id(kind.value, entity.name.strip(), entity.summary)
            tags: dict[str, Any] = {}
            if entity.aliases:
                tags["aliases"] = sorted({str(a) for a in entity.aliases})
            node = UniversalNode(
                node_id=node_id,
                kind=kind,
                title=entity.name.strip(),
                source_uri=source_uri or f"agent://{kind.value}/{node_id}",
                summary=entity.summary,
                domain_tags=tags,
                provenance=Provenance.ASSERTED,
            )
            upserts[node_id] = node
            existing_nodes.append(node)  # visible to later dedup passes
            name_to_id[entity.name.strip().lower()] = node_id
            for alias in entity.aliases:
                name_to_id.setdefault(alias.strip().lower(), node_id)

        edges: list[UniversalEdge] = []
        skipped_relations: list[str] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for relation in extracted.relations:
            src = name_to_id.get(relation.source.strip().lower())
            tgt = name_to_id.get(relation.target.strip().lower())
            if src is None or tgt is None or src == tgt:
                skipped_relations.append(
                    f"{relation.source} -{relation.kind}-> {relation.target}"
                )
                continue
            try:
                kind = EdgeKind(relation.kind)
            except ValueError:
                kind = EdgeKind.REFERENCES
            key = (src, tgt, kind.value)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append(
                UniversalEdge(source_id=src, target_id=tgt, kind=kind)
            )
        if skipped_relations:
            self.logger.warning(
                "extract_and_publish: %d relations skipped (unresolvable): %s",
                len(skipped_relations),
                "; ".join(skipped_relations[:5]),
            )

        update = GraphUpdate(
            nodes=list(upserts.values()),
            edges=edges,
            agent_id=agent_id,
            run_id=run_id,
            asserted_by=f"agent:{agent_id}",
            source=source_uri,
            reason=f"LLM extraction from {source_uri or 'text'}",
            op="extract_knowledge",
        )
        receipt = await self.publisher.publish(update)
        return ExtractionPublishResult(
            receipt=receipt, extracted=extracted, update=update
        )
