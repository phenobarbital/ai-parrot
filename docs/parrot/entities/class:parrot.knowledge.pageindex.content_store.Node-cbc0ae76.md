---
type: Wiki Entity
title: NodeContentStore
id: class:parrot.knowledge.pageindex.content_store.NodeContentStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: On-disk per-node markdown content store with a bounded LRU cache.
---

# NodeContentStore

Defined in [`parrot.knowledge.pageindex.content_store`](../summaries/mod:parrot.knowledge.pageindex.content_store.md).

```python
class NodeContentStore
```

On-disk per-node markdown content store with a bounded LRU cache.

Args:
    storage_dir: Directory that contains tree JSON files and the
        sibling ``<tree_name>/`` content directories. Created if it
        does not exist.
    cache_size: Maximum number of ``(tree_name, node_id)`` entries
        held in memory.

Notes:
    * Tree and node names are validated to keep the on-disk layout
      flat and safe from path-escape inputs.
    * The cache is per-instance; each ``PageIndexToolkit`` owns its
      own store and therefore its own cache.

## Methods

- `def save(self, tree_name: str, node_id: str, markdown: str) -> None` — Persist ``markdown`` for ``node_id`` under ``tree_name``.
- `def load(self, tree_name: str, node_id: str) -> Optional[str]` — Return the markdown for ``node_id`` or ``None`` if missing.
- `def has(self, tree_name: str, node_id: str) -> bool` — Return whether the sidecar markdown file for ``node_id`` exists.
- `def delete_node(self, tree_name: str, node_id: str) -> bool` — Remove the sidecar for ``node_id``. Returns ``True`` if removed.
- `def delete_tree(self, tree_name: str) -> int` — Remove every sidecar for ``tree_name``; return file count removed.
- `def list_node_ids(self, tree_name: str) -> list[str]` — Return node ids that currently have a sidecar on disk, sorted.
- `def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]` — Return a closure ``node_id -> Optional[str]`` for ``tree_name``.
