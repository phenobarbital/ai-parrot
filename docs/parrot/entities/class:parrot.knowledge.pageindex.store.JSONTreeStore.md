---
type: Wiki Entity
title: JSONTreeStore
id: class:parrot.knowledge.pageindex.store.JSONTreeStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: File-system backed registry of PageIndex trees.
---

# JSONTreeStore

Defined in [`parrot.knowledge.pageindex.store`](../summaries/mod:parrot.knowledge.pageindex.store.md).

```python
class JSONTreeStore
```

File-system backed registry of PageIndex trees.

Args:
    storage_dir: Directory that will hold one ``<name>.json`` file per
        tree. Created if missing.

## Methods

- `def list_names(self) -> list[str]` — Return tree names currently present on disk, sorted.
- `def exists(self, tree_name: str) -> bool`
- `def load(self, tree_name: str) -> dict[str, Any]` — Load a tree dict. Raises ``FileNotFoundError`` if absent.
- `def save(self, tree_name: str, tree: dict[str, Any]) -> None` — Atomically persist a tree to disk.
- `def delete(self, tree_name: str) -> bool`
