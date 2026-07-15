---
type: Concept
title: cohesion_for_community()
id: func:parrot.knowledge.graphindex.communities.cohesion_for_community
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: internal_edges / (internal_edges + boundary_edges).
---

# cohesion_for_community

```python
def cohesion_for_community(nx_graph: nx.Graph, members: set[str]) -> float
```

internal_edges / (internal_edges + boundary_edges).

Returns 0.0 when the community has no incident edges (graph
isolates yield singletons with zero cohesion by definition).
