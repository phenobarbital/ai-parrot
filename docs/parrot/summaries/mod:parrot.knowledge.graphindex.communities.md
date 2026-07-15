---
type: Wiki Summary
title: parrot.knowledge.graphindex.communities
id: mod:parrot.knowledge.graphindex.communities
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Louvain community detection for GraphIndex (FEAT-191).
relates_to:
- concept: class:parrot.knowledge.graphindex.communities.CommunitiesResult
  rel: defines
- concept: class:parrot.knowledge.graphindex.communities.Community
  rel: defines
- concept: func:parrot.knowledge.graphindex.communities.cohesion_for_community
  rel: defines
- concept: func:parrot.knowledge.graphindex.communities.derive_community_label
  rel: defines
- concept: func:parrot.knowledge.graphindex.communities.detect_communities
  rel: defines
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.graphindex.signals
  rel: references
---

# `parrot.knowledge.graphindex.communities`

Louvain community detection for GraphIndex (FEAT-191).

Runs Louvain modularity-maximisation over the assembled
``rustworkx.PyDiGraph`` via networkx (rustworkx 0.17 has no community
detection), computes per-community cohesion + global modularity, and
writes a stable ``community_id`` onto every node's ``domain_tags``
so the assignment round-trips through
:func:`parrot.knowledge.graphindex.persist._node_to_doc` to ArangoDB
with zero persist-layer changes.

Optionally consumes :class:`SignalRelevanceConfig` (FEAT-190) to weight
edges by ``signal_relevance(a, b).combined`` before Louvain runs, so
community boundaries respect the signal model rather than raw edge
counts. The FEAT-190 import is lazy — FEAT-191 ships standalone.

## Classes

- **`Community(BaseModel)`** — A single community in the partition.
- **`CommunitiesResult(BaseModel)`** — Full Louvain partition + per-community metadata.

## Functions

- `def derive_community_label(titles: Iterable[str], max_terms: int=3) -> str` — Derive a deterministic, LLM-free label from member titles.
- `def cohesion_for_community(nx_graph: nx.Graph, members: set[str]) -> float` — internal_edges / (internal_edges + boundary_edges).
- `def detect_communities(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], resolution: float=1.0, seed: int=42, signal_config: Optional['SignalRelevanceConfig']=None, embedder: Optional[object]=None, write_back_to_nodes: bool=True) -> CommunitiesResult` — Run Louvain community detection on the assembled graph.
