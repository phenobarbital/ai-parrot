---
type: Wiki Summary
title: parrot.knowledge.graphindex.analytics
id: mod:parrot.knowledge.graphindex.analytics
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Analytics + Report stage for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.analytics.AnalyticsResult
  rel: defines
- concept: class:parrot.knowledge.graphindex.analytics.DismissedInsights
  rel: defines
- concept: class:parrot.knowledge.graphindex.analytics.KnowledgeGaps
  rel: defines
- concept: class:parrot.knowledge.graphindex.analytics.SurpriseFactors
  rel: defines
- concept: func:parrot.knowledge.graphindex.analytics.compute_analytics
  rel: defines
- concept: func:parrot.knowledge.graphindex.analytics.dismiss_insight
  rel: defines
- concept: func:parrot.knowledge.graphindex.analytics.find_bridge_nodes
  rel: defines
- concept: func:parrot.knowledge.graphindex.analytics.find_isolated_nodes
  rel: defines
- concept: func:parrot.knowledge.graphindex.analytics.find_sparse_communities
  rel: defines
- concept: func:parrot.knowledge.graphindex.analytics.generate_report
  rel: defines
- concept: func:parrot.knowledge.graphindex.analytics.list_unreviewed_insights
  rel: defines
- concept: mod:parrot.knowledge.graphindex.communities
  rel: references
- concept: mod:parrot.knowledge.graphindex.projection
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.analytics`

Analytics + Report stage for GraphIndex.

Computes centrality metrics to identify "god-nodes", ranks cross-domain
``mentions`` edges by confidence to surface surprising connections, and
generates a deterministic ``GRAPH_REPORT.md`` for agent consumption.

v1 uses deterministic templates only.  The ``llm_polish`` flag is accepted
but is a no-op; LLM-polished reports are planned for v1.5.

## Classes

- **`KnowledgeGaps(BaseModel)`** — Aggregated knowledge gap report.
- **`SurpriseFactors(BaseModel)`** — Decomposed explanation of why a connection is surprising.
- **`DismissedInsights(BaseModel)`** — Tracks dismissed insight IDs. Session-scoped (not persisted to DB).
- **`AnalyticsResult`** — Results from graph analytics computation.

## Functions

- `def compute_analytics(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], edges: list[UniversalEdge], top_k: int=10) -> AnalyticsResult` — Compute centrality metrics and rank cross-domain connections.
- `def find_isolated_nodes(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], max_degree: int=1, exclude_kinds: Optional[set[NodeKind]]=None) -> list[dict]` — Find nodes with few connections (potential knowledge gaps).
- `def find_sparse_communities(communities_result: Optional['CommunitiesResult'], min_size: int=3, max_cohesion: float=0.15) -> list[dict]` — Find communities with low internal cohesion (sparse communities).
- `def find_bridge_nodes(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], communities_result: Optional['CommunitiesResult'], min_communities: int=3) -> list[dict]` — Find nodes that bridge multiple distinct communities.
- `def dismiss_insight(analytics: AnalyticsResult, insight_id: str) -> None` — Mark an insight as dismissed.
- `def list_unreviewed_insights(analytics: AnalyticsResult) -> list[dict]` — Return all insights not yet dismissed.
- `def generate_report(analytics: AnalyticsResult, output_dir: Path, llm_polish: bool=False, tenant_id: str='default') -> Path` — Generate ``GRAPH_REPORT.md`` from analytics results.
