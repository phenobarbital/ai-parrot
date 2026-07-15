---
type: Wiki Entity
title: GraphAssembler
id: class:parrot.knowledge.graphindex.assemble.GraphAssembler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build and query a rustworkx PyDiGraph from UniversalNode/UniversalEdge streams.
---

# GraphAssembler

Defined in [`parrot.knowledge.graphindex.assemble`](../summaries/mod:parrot.knowledge.graphindex.assemble.md).

```python
class GraphAssembler
```

Build and query a rustworkx PyDiGraph from UniversalNode/UniversalEdge streams.

Maintains per-tenant graph isolation.  Node payloads are lightweight
metadata dicts (IDs, kind, title, domain_tags); source content is
referenced via ``content_ref``, not stored in the graph.

Args:
    tenant_id: Tenant identifier for graph isolation.

## Methods

- `def add_node(self, node: UniversalNode) -> int` — Add a node to the graph. Updates existing payload on duplicate ``node_id``.
- `def add_edge(self, edge: UniversalEdge) -> Optional[int]` — Add an edge to the graph. Skips if source/target missing.
- `def add_nodes(self, nodes: list[UniversalNode]) -> list[int]` — Batch-add nodes to the graph.
- `def add_edges(self, edges: list[UniversalEdge]) -> list[Optional[int]]` — Batch-add edges to the graph.
- `def get_node(self, node_id: str) -> Optional[dict]` — Get node payload by ``node_id``.
- `def get_neighbors(self, node_id: str, direction: str='outgoing') -> list[dict]` — Get neighboring node payloads.
- `def get_edges_for_node(self, node_id: str, direction: str='both') -> list[dict]` — Get edge payloads connected to a node.
- `def node_count(self) -> int` — Number of nodes in the graph.
- `def edge_count(self) -> int` — Number of edges in the graph.
