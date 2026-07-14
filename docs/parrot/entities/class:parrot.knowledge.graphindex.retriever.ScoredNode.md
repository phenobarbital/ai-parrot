---
type: Wiki Entity
title: ScoredNode
id: class:parrot.knowledge.graphindex.retriever.ScoredNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A retrieval candidate with decomposed scores.
---

# ScoredNode

Defined in [`parrot.knowledge.graphindex.retriever`](../summaries/mod:parrot.knowledge.graphindex.retriever.md).

```python
class ScoredNode(BaseModel)
```

A retrieval candidate with decomposed scores.

Args:
    node_id: Unique node identifier within the graph.
    title: Human-readable display name of the node.
    kind: Semantic category string (e.g. ``"document"``, ``"concept"``).
    search_score: Normalised score ``[0, 1]`` from the Phase 1 seed
        search (0.0 for expanded nodes that were not seeds).
    signal_score: ``SignalRelevance.combined`` value used during
        expansion (0.0 for seed nodes).
    decay_factor: Cumulative decay applied: ``decay_base^hop_distance``
        (1.0 for seeds).
    combined_score: Effective ranking score: the product of parent's
        combined score, decay, and signal.  For seeds this equals
        ``search_score``.
    hop_distance: Number of hops from the nearest seed (0 for seeds
        themselves).
    community_id: Community identifier assigned in Phase 3, or ``None``
        when Phase 3 is skipped.
    community_cohesion: Cohesion score of the node's community, or
        ``None``.
    is_seed: ``True`` if this node was returned by Phase 1 seed search.
    source_uri: Source URI of the underlying document or artefact.
    summary: Short textual summary of the node content, if available.
