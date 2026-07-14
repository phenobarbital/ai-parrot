---
type: Wiki Summary
title: parrot.knowledge.pageindex.content_store
id: mod:parrot.knowledge.pageindex.content_store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-node markdown content store for PageIndex trees.
relates_to:
- concept: class:parrot.knowledge.pageindex.content_store.NodeContentStore
  rel: defines
---

# `parrot.knowledge.pageindex.content_store`

Per-node markdown content store for PageIndex trees.

Each PageIndex node references markdown content stored alongside the
tree JSON in a sibling directory::

    <storage_dir>/
        <tree_name>.json          ← INDEX (lean ToC tree)
        <tree_name>/              ← CONTENT (one .md per node)
            0000.md
            0001.md
            …

The store fronts disk reads with a bounded LRU cache keyed by
``(tree_name, node_id)`` so repeated retrieval of the same node is
served from memory. Cache entries are evicted on save/delete so writers
and readers never observe stale content.

This module deliberately uses only the standard library — file I/O is
fast enough for the access patterns PageIndex exercises, and wrapping
small reads in async would add noise without benefit.

## Classes

- **`NodeContentStore`** — On-disk per-node markdown content store with a bounded LRU cache.
