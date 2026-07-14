---
type: Concept
title: export_okf_bundle()
id: func:parrot.knowledge.pageindex.okf.bundle.export_okf_bundle
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Export a PageIndex tree as an OKF v0.1 compliant directory bundle.
---

# export_okf_bundle

```python
def export_okf_bundle(tree: dict, tree_name: str, content_store: NodeContentStore, output_dir: Path) -> ExportReport
```

Export a PageIndex tree as an OKF v0.1 compliant directory bundle.

Creates a directory hierarchy grouped by concept ``type``:
``policies/``, ``controls/``, ``sections/``, etc.  Each ``.md`` file
contains OKF-standard YAML frontmatter (no ``node_id``, no
``pageindex://`` URIs) followed by the body content.

A root ``index.md`` is generated via
:func:`~parrot.knowledge.pageindex.okf.projection.generate_index_md`.

Args:
    tree: OKF-enriched PageIndex tree dict.
    tree_name: Name of the tree (used in URI rewriting and index title).
    content_store: :class:`~parrot.knowledge.pageindex.content_store.NodeContentStore`
        for loading sidecar bodies.
    output_dir: Destination directory.  Created if absent.

Returns:
    :class:`ExportReport` with counts of files written and URIs rewritten.
