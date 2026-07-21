---
type: Concept
title: reindex_node_ids()
id: func:parrot.knowledge.pageindex.tree_ops.reindex_node_ids
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Reassign sequential 4-digit ``node_id`` values across the tree.
---

# reindex_node_ids

```python
def reindex_node_ids(tree: dict[str, Any]) -> None
```

Reassign sequential 4-digit ``node_id`` values across the tree.

Only ``node_id`` is modified.  OKF fields (``concept_id``, ``type``,
``source``, ``relates_to``) are never touched — ``concept_id`` in
particular is a stable identity anchor that must survive renumbering.
