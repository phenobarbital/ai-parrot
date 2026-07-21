---
type: Concept
title: node_to_frontmatter_dict()
id: func:parrot.knowledge.graphindex.projection.node_to_frontmatter_dict
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert a UniversalNode + its outgoing edges into a project_frontmatter()
  dict.
---

# node_to_frontmatter_dict

```python
def node_to_frontmatter_dict(node: UniversalNode, edges: list[UniversalEdge]) -> dict
```

Convert a UniversalNode + its outgoing edges into a project_frontmatter() dict.

The returned dict conforms to the contract expected by
``project_frontmatter(node_dict, tree_name)``.  It is a pure function
with no I/O — the same inputs always produce the same output.

Args:
    node: The GraphIndex node to project.
    edges: All edges in the graph.  Only outgoing edges from ``node``
        are included in ``relates_to``.

Returns:
    Dict suitable for ``project_frontmatter(dict, "graphindex")``.
