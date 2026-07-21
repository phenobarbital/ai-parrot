---
type: Concept
title: assign_concept_ids()
id: func:parrot.knowledge.pageindex.okf.concept_id.assign_concept_ids
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Walk the tree depth-first and write deterministic ``concept_id`` values.
---

# assign_concept_ids

```python
def assign_concept_ids(tree: dict[str, Any]) -> None
```

Walk the tree depth-first and write deterministic ``concept_id`` values.

This is the public entry point for enriching a bare PageIndex tree with
``concept_id`` fields.  Running twice on the same tree produces identical
values (idempotent and deterministic).

The function:
1. Walks the tree depth-first via ``structure``.
2. Derives a slug for each node via ``derive_concept_id``.
3. Resolves per-level collisions via sibling-scoped dedup in
   ``_assign_recursive`` — children always inherit the post-dedup
   parent path.

Note:
    The global ``dedup_concept_ids`` step that previously ran here
    has been moved into ``_assign_recursive`` so that sibling dedup
    happens before recursing into children.  ``dedup_concept_ids``
    remains public for callers that maintain their own flat node lists.

Args:
    tree: PageIndex tree dict with a ``structure`` list of node dicts.
        Modified in place.
