---
type: Concept
title: splice_subtree()
id: func:parrot.knowledge.pageindex.tree_ops.splice_subtree
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Insert ``subtree`` under ``parent_node_id`` (or at root if None).
---

# splice_subtree

```python
def splice_subtree(target: dict[str, Any], subtree: dict[str, Any] | list[dict[str, Any]], parent_node_id: Optional[str]=None) -> list[str]
```

Insert ``subtree`` under ``parent_node_id`` (or at root if None).

Returns the new ``node_id`` of each freshly spliced root node, taken
after the tree-wide reindex.

After splicing and reindexing, ``assign_concept_ids`` is called on
the whole target tree so that any new nodes arriving without a
``concept_id`` receive one.  Existing ``concept_id`` values on all
nodes (pre-existing and newly spliced) are preserved.
