"""Task-scoped context construction from a knowledge graph.

Implements the paper's graph-grounded context recipe: resolve the
entities a task mentions, expand a bounded neighbourhood over allowed
edge types, prefer recent verified (asserted) claims, surface conflicts
explicitly, and serialize everything within a token budget — with a
stable, citable id attached to every relation so downstream evaluators
can check answers edge-by-edge instead of trusting free-form prose.

The builder is a thin composition over :class:`GraphExpandedRetriever`
(which already provides seeded search, decayed multi-hop expansion, and
budgeting) — the deltas here are entity seeding, edge-kind filtering,
assertion-aware ranking, conflict surfacing, and citation serialization.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.graphindex.retriever import (
    BudgetConfig,
    ExpansionConfig,
    GraphExpandedRetriever,
    ScoredNode,
)
from parrot.knowledge.graphindex.schema import stable_edge_id

if TYPE_CHECKING:  # pragma: no cover — typing only
    from parrot.knowledge.graphindex.schema import UniversalNode

logger = logging.getLogger(__name__)

#: Minimum title length considered for entity resolution by mention.
_MIN_ENTITY_TITLE = 3


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate (≈4 chars/token) — good enough for budgeting."""
    return max(1, len(text) // 4)


class ContextBuildConfig(BaseModel):
    """Configuration for graph context construction.

    Args:
        allowed_edge_kinds: Restrict expansion (and cited relations) to
            these edge kinds. ``None`` allows every kind.
        max_hops: Neighbourhood radius around resolved/seeded entities.
        max_tokens: Serialization budget for the final context text.
        seed_top_k: Seed-search breadth before expansion.
        include_conflicts: Surface ambiguous/contradicting relations in a
            dedicated section instead of hiding them.
        prefer_asserted: Boost nodes carrying assertion metadata (agent/
            human-verified claims) above same-scored extracted nodes.
        max_entities: Cap on entity mentions resolved from the task text.
    """

    allowed_edge_kinds: Optional[list[str]] = None
    max_hops: int = Field(default=2, ge=1, le=4)
    max_tokens: int = Field(default=4000, ge=200)
    seed_top_k: int = Field(default=8, ge=1)
    include_conflicts: bool = True
    prefer_asserted: bool = True
    max_entities: int = Field(default=10, ge=1)


class GraphContext(BaseModel):
    """Serialized, citable graph context for one task.

    Args:
        text: Markdown context ready for prompt injection.
        entities: ``node_id`` of every entity resolved from the task.
        node_ids: Every node included in the context.
        cited_edge_ids: Stable edge ids (see :func:`stable_edge_id`)
            attached to the serialized relations, for citation.
        conflicts: Stable edge ids of surfaced conflict relations.
        budget_used: Estimated tokens consumed by ``text``.
        truncated: Whether the budget cut content.
    """

    text: str
    entities: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    cited_edge_ids: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    budget_used: int = 0
    truncated: bool = False


class GraphContextBuilder:
    """Build task-specific, token-budgeted context from a graph.

    Args:
        retriever: A :class:`GraphExpandedRetriever` over the graph.
        entity_resolver: Optional resolver with an async
            ``extract_and_resolve(text)`` API; when absent, entities are
            resolved by (case-insensitive) title mention matching —
            dependency-free and adequate for agent-memory graphs.
    """

    def __init__(
        self,
        retriever: GraphExpandedRetriever,
        entity_resolver: Optional[object] = None,
    ) -> None:
        self.retriever = retriever
        self.entity_resolver = entity_resolver
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Step 1 — entity resolution
    # ------------------------------------------------------------------

    async def _resolve_entities(
        self, task: str, config: ContextBuildConfig
    ) -> list[str]:
        """Resolve task-mentioned entities to graph node ids."""
        if self.entity_resolver is not None:
            try:
                resolved = await self.entity_resolver.extract_and_resolve(task)
                ids = [
                    str(getattr(e, "node_id", None) or e.get("node_id"))
                    for e in (resolved or [])
                ]
                return [i for i in ids if i][: config.max_entities]
            except Exception as exc:  # noqa: BLE001 — fall back to mentions
                self.logger.debug(
                    "entity resolver failed (%s); using mention matching", exc
                )
        task_lower = task.lower()
        matches: list[tuple[int, str]] = []
        for node in self.retriever.nodes:
            title = (node.title or "").strip()
            if len(title) < _MIN_ENTITY_TITLE:
                continue
            candidates = [title.lower()]
            aliases = node.domain_tags.get("aliases") or []
            candidates += [str(a).lower() for a in aliases if a]
            for cand in candidates:
                if cand and cand in task_lower:
                    matches.append((len(cand), node.node_id))
                    break
        # Longest mentions first — most specific entities win the cap.
        matches.sort(reverse=True)
        seen: set[str] = set()
        ordered: list[str] = []
        for _, node_id in matches:
            if node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        return ordered[: config.max_entities]

    # ------------------------------------------------------------------
    # Step 2+3 — retrieval and assertion-aware ranking
    # ------------------------------------------------------------------

    def _node_meta(self, node_id: str) -> Optional["UniversalNode"]:
        for node in self.retriever.nodes:
            if node.node_id == node_id:
                return node
        return None

    def _rank(
        self, nodes: list[ScoredNode], config: ContextBuildConfig
    ) -> list[ScoredNode]:
        """Order candidates; asserted (verified) claims first when enabled."""

        def sort_key(sn: ScoredNode) -> tuple:
            meta = self._node_meta(sn.node_id)
            asserted = bool(meta is not None and meta.assertion is not None)
            asserted_at = (
                meta.assertion.asserted_at
                if asserted and meta.assertion.asserted_at
                else ""
            )
            if config.prefer_asserted:
                return (asserted, sn.combined_score, asserted_at)
            return (sn.combined_score, asserted, asserted_at)

        return sorted(nodes, key=sort_key, reverse=True)

    # ------------------------------------------------------------------
    # Step 4 — relations among included nodes
    # ------------------------------------------------------------------

    def _relations(
        self, node_ids: list[str], config: ContextBuildConfig
    ) -> tuple[list[dict], list[dict]]:
        """Collect (relations, conflicts) among the included nodes.

        A relation is a conflict when its provenance is ``ambiguous`` or
        its kind is ``contradicts``.
        """
        included = set(node_ids)
        allowed = (
            set(config.allowed_edge_kinds) if config.allowed_edge_kinds else None
        )
        graph = self.retriever.graph
        titles: dict[str, str] = {}
        for node in self.retriever.nodes:
            titles[node.node_id] = node.title

        relations: list[dict] = []
        conflicts: list[dict] = []
        seen: set[str] = set()
        for idx in graph.node_indices():
            payload = graph[idx]
            if not isinstance(payload, dict):
                continue
            src = payload.get("node_id")
            if src not in included:
                continue
            for _s, t, edge in graph.out_edges(idx):
                if not isinstance(edge, dict):
                    continue
                dst = edge.get("target_id")
                kind = edge.get("kind")
                if dst not in included or not kind:
                    continue
                is_conflict = (
                    edge.get("provenance") == "ambiguous" or kind == "contradicts"
                )
                if allowed is not None and kind not in allowed and not is_conflict:
                    continue
                edge_id = stable_edge_id(src, dst, kind)
                if edge_id in seen:
                    continue
                seen.add(edge_id)
                entry = {
                    "edge_id": edge_id,
                    "src": src,
                    "dst": dst,
                    "kind": kind,
                    "src_title": titles.get(src, src),
                    "dst_title": titles.get(dst, dst),
                    "provenance": edge.get("provenance", "extracted"),
                }
                if is_conflict:
                    conflicts.append(entry)
                else:
                    relations.append(entry)
        return relations, conflicts

    # ------------------------------------------------------------------
    # Step 5 — serialization within budget
    # ------------------------------------------------------------------

    async def build(
        self,
        task: str,
        config: Optional[ContextBuildConfig] = None,
    ) -> GraphContext:
        """Build the serialized graph context for a task.

        Args:
            task: The task/question the context should ground.
            config: Optional build configuration.

        Returns:
            A :class:`GraphContext` with citable relations.
        """
        config = config or ContextBuildConfig()

        entity_ids = await self._resolve_entities(task, config)

        result = await self.retriever.search(
            task,
            seed_top_k=config.seed_top_k,
            expansion=ExpansionConfig(
                max_hops=config.max_hops,
                allowed_edge_kinds=config.allowed_edge_kinds,
            ),
            budget=BudgetConfig(max_tokens=config.max_tokens),
        )
        candidates = {sn.node_id: sn for sn in result.nodes}
        # Force-include resolved entities even when seed search missed them.
        for node_id in entity_ids:
            if node_id not in candidates:
                meta = self._node_meta(node_id)
                if meta is None:
                    continue
                candidates[node_id] = ScoredNode(
                    node_id=node_id,
                    title=meta.title,
                    kind=str(meta.kind.value)
                    if hasattr(meta.kind, "value")
                    else str(meta.kind),
                    search_score=1.0,
                    combined_score=1.0,
                    is_seed=True,
                    source_uri=meta.source_uri,
                    summary=meta.summary,
                )

        ranked = self._rank(list(candidates.values()), config)

        # Serialize greedily within budget.
        header = f"## Graph context\n\nTask: {task.strip()[:160]}\n"
        lines: list[str] = [header]
        budget_used = _estimate_tokens(header)
        truncated = False
        included: list[str] = []

        if entity_ids:
            entity_lines = ["\n### Entities in this task\n"]
            for node_id in entity_ids:
                meta = self._node_meta(node_id)
                if meta is not None:
                    entity_lines.append(f"- {meta.title} [{node_id}]\n")
            block = "".join(entity_lines)
            lines.append(block)
            budget_used += _estimate_tokens(block)

        lines.append("\n### Knowledge\n")
        for sn in ranked:
            meta = self._node_meta(sn.node_id)
            attribution = ""
            if meta is not None and meta.assertion is not None:
                attribution = (
                    f" (asserted by {meta.assertion.asserted_by}"
                    f"{' @ ' + meta.assertion.asserted_at if meta.assertion.asserted_at else ''})"
                )
            summary = (sn.summary or "").strip().replace("\n", " ")
            line = (
                f"- [{sn.node_id}] {sn.title} ({sn.kind};"
                f" score {sn.combined_score:.2f}){attribution}"
                + (f" — {summary[:200]}" if summary else "")
                + "\n"
            )
            cost = _estimate_tokens(line)
            if budget_used + cost > config.max_tokens:
                truncated = True
                break
            lines.append(line)
            budget_used += cost
            included.append(sn.node_id)

        relations, conflicts = self._relations(included, config)
        cited: list[str] = []
        if relations:
            rel_header = "\n### Relations (cite by edge id)\n"
            lines.append(rel_header)
            budget_used += _estimate_tokens(rel_header)
            for rel in relations:
                line = (
                    f"- [edge:{rel['edge_id']}] {rel['src_title']}"
                    f" -{rel['kind']}-> {rel['dst_title']}\n"
                )
                cost = _estimate_tokens(line)
                if budget_used + cost > config.max_tokens:
                    truncated = True
                    break
                lines.append(line)
                budget_used += cost
                cited.append(rel["edge_id"])

        conflict_ids: list[str] = []
        if conflicts and config.include_conflicts:
            conflict_header = "\n### Conflicts / uncertain claims\n"
            lines.append(conflict_header)
            budget_used += _estimate_tokens(conflict_header)
            for rel in conflicts:
                line = (
                    f"- [edge:{rel['edge_id']}] {rel['src_title']}"
                    f" -{rel['kind']}-> {rel['dst_title']}"
                    f" (provenance={rel['provenance']})\n"
                )
                cost = _estimate_tokens(line)
                if budget_used + cost > config.max_tokens:
                    truncated = True
                    break
                lines.append(line)
                budget_used += cost
                conflict_ids.append(rel["edge_id"])
                cited.append(rel["edge_id"])

        return GraphContext(
            text="".join(lines),
            entities=entity_ids,
            node_ids=included,
            cited_edge_ids=cited,
            conflicts=conflict_ids,
            budget_used=budget_used,
            truncated=truncated,
        )
