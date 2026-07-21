---
type: Concept
title: project_sidecars()
id: func:parrot.knowledge.pageindex.okf.projection.project_sidecars
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Regenerate all sidecars from the authoritative JSON tree.
---

# project_sidecars

```python
def project_sidecars(tree: dict, tree_name: str, content_store: NodeContentStore) -> ProjectionReport
```

Regenerate all sidecars from the authoritative JSON tree.

For each node in the tree:
1. Derive the flat concept_id filename.
2. Load the existing body (try concept_id key first, then node_id).
3. Combine frontmatter + body and write via ``content_store.save()``.
4. Remove the old ``<node_id>.md`` file if a different key was used.

This function is byte-deterministic: two runs on the same tree JSON
produce identical file contents.

Args:
    tree: OKF-enriched PageIndex tree dict (all nodes must have
        ``concept_id``).
    tree_name: PageIndex tree name.
    content_store: NodeContentStore instance for reading/writing sidecars.

Returns:
    ``ProjectionReport`` with counts and filenames of written/removed files.
