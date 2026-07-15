---
type: Wiki Summary
title: parrot.knowledge.graphindex.signals
id: mod:parrot.knowledge.graphindex.signals
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Signal Knowledge Graph relevance model for GraphIndex (FEAT-190).
relates_to:
- concept: class:parrot.knowledge.graphindex.signals.SignalRelevance
  rel: defines
- concept: class:parrot.knowledge.graphindex.signals.SignalRelevanceConfig
  rel: defines
- concept: func:parrot.knowledge.graphindex.signals.compute_pairwise_signals
  rel: defines
- concept: func:parrot.knowledge.graphindex.signals.relevance_neighborhood
  rel: defines
- concept: func:parrot.knowledge.graphindex.signals.signal_relevance
  rel: defines
- concept: mod:parrot.knowledge.graphindex.embed
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.signals`

Signal Knowledge Graph relevance model for GraphIndex (FEAT-190).

Five orthogonal pairwise signals between two ``UniversalNode`` instances,
combined into a single decomposed :class:`SignalRelevance` so an LLM
consumer can read *why* two nodes are related, not just a number:

1. **Direct links** — weighted sum over `EdgeKind` of edges that connect
   the pair in either direction.
2. **Source overlap** — Jaccard similarity over ``source_uri`` sets.
3. **Adamic-Adar** — shared-neighbour signal weighting rare connectors
   more than hubs. Via :mod:`networkx` (rustworkx 0.17 has no AA).
4. **Type affinity** — configurable ``NodeKind × NodeKind`` matrix.
5. **Embedding similarity** — cosine over FAISS-backed vectors. Opt-in
   via dependency injection of a :class:`GraphIndexEmbedder`. When
   absent, the four structural weights auto-renormalise to 1.0 so the
   combined score stays interpretable.

All sub-scores live in ``[0, 1]``. The combined score therefore lives
in ``[0, 1]`` whenever the configured weights sum to 1.0 (enforced by
:class:`SignalRelevanceConfig`).

## Classes

- **`SignalRelevanceConfig(BaseModel)`** — Configuration for the five-signal relevance scorer.
- **`SignalRelevance(BaseModel)`** — Decomposed pairwise relevance result.

## Functions

- `def signal_relevance(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], node_a: str, node_b: str, config: Optional[SignalRelevanceConfig]=None, embedder: Optional['GraphIndexEmbedder']=None) -> SignalRelevance` — Pairwise five-signal relevance over an assembled GraphIndex.
- `def compute_pairwise_signals(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], node_a: str, node_b: str, embedder: Optional['GraphIndexEmbedder']=None) -> dict[str, float]` — Raw five signals without combination. Cheap building block.
- `def relevance_neighborhood(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], node_id: str, top_k: int=10, config: Optional[SignalRelevanceConfig]=None, candidate_pool: Optional[Iterable[str]]=None, embedder: Optional['GraphIndexEmbedder']=None) -> list[SignalRelevance]` — Top-K nodes most relevant to ``node_id`` by combined score.
