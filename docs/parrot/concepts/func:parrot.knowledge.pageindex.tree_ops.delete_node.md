---
type: Concept
title: delete_node()
id: func:parrot.knowledge.pageindex.tree_ops.delete_node
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Remove the node with ``node_id`` and all its descendants.
---

# delete_node

```python
def delete_node(tree: dict[str, Any], node_id: str) -> bool
```

Remove the node with ``node_id`` and all its descendants.

Returns ``True`` if a node was removed, ``False`` if not found.
