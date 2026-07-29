---
type: Concept
title: find_bridge_nodes()
id: func:parrot.knowledge.graphindex.analytics.find_bridge_nodes
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Find nodes that bridge multiple distinct communities.
---

# find_bridge_nodes

```python
def find_bridge_nodes(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], communities_result: Optional['CommunitiesResult'], min_communities: int=3) -> list[dict]
```

Find nodes that bridge multiple distinct communities.

A bridge node is one whose neighbors span at least ``min_communities``
distinct Louvain communities. These nodes are critical connectors
and represent important cross-domain knowledge links.

Args:
    graph: The assembled PyDiGraph.
    nodes: All ``UniversalNode`` objects in the graph.
    communities_result: A ``CommunitiesResult`` from FEAT-191 Louvain
        community detection.
    min_communities: Minimum number of distinct neighbor communities
        required to classify a node as a bridge. Defaults to 3.

Returns:
    List of dicts, each containing ``node_id``, ``title``, ``kind``,
    ``community_count``, and ``neighbor_community_ids`` for bridge nodes.
