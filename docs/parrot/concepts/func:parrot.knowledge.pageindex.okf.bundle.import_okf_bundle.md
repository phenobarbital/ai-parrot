---
type: Concept
title: import_okf_bundle()
id: func:parrot.knowledge.pageindex.okf.bundle.import_okf_bundle
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Import an OKF bundle directory into a new PageIndex tree.
---

# import_okf_bundle

```python
def import_okf_bundle(input_dir: Path, tree_name: str, store: JSONTreeStore, content_store: NodeContentStore) -> ImportReport
```

Import an OKF bundle directory into a new PageIndex tree.

Reads all ``.md`` files in ``input_dir`` recursively (skipping
``index.md``).  For each file:

1. Parses YAML frontmatter; unknown ``type`` values map to
   :data:`ConceptType.OTHER`.
2. Creates a PageIndex node with the frontmatter data.
3. Parses markdown links from the body and maps them to ``relates_to``
   edges using a ``stem → concept_id`` map built in a first pass.

The resulting tree is saved via ``store`` and bodies via
``content_store``.

.. note::
    If a tree named ``tree_name`` already exists in ``store`` it will be
    **overwritten** atomically.  To avoid data loss, choose a unique
    ``tree_name`` or delete the existing tree first.

Args:
    input_dir: Source OKF bundle directory.
    tree_name: Name to assign to the new (or replacement) PageIndex tree.
    store: :class:`~parrot.knowledge.pageindex.store.JSONTreeStore` for
        persisting the new tree.
    content_store: :class:`~parrot.knowledge.pageindex.content_store.NodeContentStore`
        for storing sidecar bodies.

Returns:
    :class:`ImportReport` with counts of nodes and edges created.
