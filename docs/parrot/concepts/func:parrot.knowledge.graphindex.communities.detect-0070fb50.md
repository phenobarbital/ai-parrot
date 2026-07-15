---
type: Concept
title: detect_communities()
id: func:parrot.knowledge.graphindex.communities.detect_communities
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Run Louvain community detection on the assembled graph.
---

# detect_communities

```python
def detect_communities(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], resolution: float=1.0, seed: int=42, signal_config: Optional['SignalRelevanceConfig']=None, embedder: Optional[object]=None, write_back_to_nodes: bool=True) -> CommunitiesResult
```

Run Louvain community detection on the assembled graph.

Args:
    graph: The assembled PyDiGraph.
    nodes: The UniversalNode list; mutated in-place when
        ``write_back_to_nodes=True``.
    resolution: Louvain γ resolution parameter. >1.0 finds smaller
        (tighter) communities; <1.0 finds larger ones.
    seed: RNG seed for deterministic results across builds.
    signal_config: Optional FEAT-190 config; when set, edges are
        weighted by ``signal_relevance(a, b).combined`` before
        Louvain runs.
    embedder: Optional embedder forwarded to FEAT-190 when computing
        edge weights (ignored unless ``signal_config`` is set).
    write_back_to_nodes: When True (default), writes
        ``domain_tags['community_id']`` into every node and
        ``domain_tags['community_centroid']=True`` for each centroid.

Returns:
    :class:`CommunitiesResult` with global modularity, the
    partition, and a `node_id → community_id` lookup.
