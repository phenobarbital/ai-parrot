---
type: Concept
title: find_isolated_nodes()
id: func:parrot.knowledge.graphindex.analytics.find_isolated_nodes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Find nodes with few connections (potential knowledge gaps).
---

# find_isolated_nodes

```python
def find_isolated_nodes(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], max_degree: int=1, exclude_kinds: Optional[set[NodeKind]]=None) -> list[dict]
```

Find nodes with few connections (potential knowledge gaps).

Nodes with total degree (in + out) <= max_degree are considered
isolated. By default, DOCUMENT nodes are excluded because they are
structural root nodes expected to have low out-degree.

Args:
    graph: The assembled PyDiGraph. Node payloads must contain
        ``node_id``, ``kind``, and ``title`` keys.
    nodes: All ``UniversalNode`` objects in the graph.
    max_degree: Maximum total degree (in + out) for a node to be
        considered isolated. Defaults to 1.
    exclude_kinds: Set of ``NodeKind`` values to skip. Defaults to
        ``{NodeKind.DOCUMENT}`` when not supplied.

Returns:
    List of dicts, each containing ``node_id``, ``title``, ``kind``,
    and ``degree`` for isolated nodes.
