---
type: Concept
title: project_node_sidecar()
id: func:parrot.knowledge.graphindex.projection.project_node_sidecar
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Return the complete sidecar text: YAML frontmatter + body.'
---

# project_node_sidecar

```python
def project_node_sidecar(node: UniversalNode, edges: list[UniversalEdge], body: str) -> str
```

Return the complete sidecar text: YAML frontmatter + body.

The output is byte-deterministic: the same ``node``, ``edges``, and
``body`` always produce the same result.

Args:
    node: The GraphIndex node to project.
    edges: All edges (outgoing edges from node become ``relates_to``).
    body: Full text body for the sidecar (may be full content or summary).

Returns:
    Complete sidecar string starting with ``---\n`` frontmatter.
