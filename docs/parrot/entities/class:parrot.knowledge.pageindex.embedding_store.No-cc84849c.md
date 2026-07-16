---
type: Wiki Entity
title: NodeEmbeddingStore
id: class:parrot.knowledge.pageindex.embedding_store.NodeEmbeddingStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Two-tier content-addressed embedding cache for PageIndex trees.
---

# NodeEmbeddingStore

Defined in [`parrot.knowledge.pageindex.embedding_store`](../summaries/mod:parrot.knowledge.pageindex.embedding_store.md).

```python
class NodeEmbeddingStore
```

Two-tier content-addressed embedding cache for PageIndex trees.

Global tier: per-node embedding vectors keyed by
    ``sha1(model_id + "\x00" + title + "\x00" + summary)``.
Per-tree tier: materialized ``(N, d)`` contiguous numpy matrix,
    rebuilt on ``build_tree_matrix()``; mmap for fast matmul.

The store is model-agnostic — the caller supplies an ``embed_fn``
to ``build_tree_matrix()``.  This keeps model loading in the toolkit
and the store as a pure caching / persistence layer.

Args:
    storage_dir: Directory for sidecar ``.npy`` files.  Created on
        first write if it does not exist.
    model_id: Embedding model identifier used in the content key.
        Changing this effectively invalidates all existing entries
        (new hash, no collision with old).
    dimension: Embedding vector dimension.  Used to validate loaded
        vectors but not enforced at write time — mismatches will
        surface at matmul time.
    cache_size: Maximum number of content-key → vector entries held in
        the in-memory LRU cache.

Notes:
    * Global-tier writes are idempotent — the same content key always
      produces the same vector, so concurrent writers cannot corrupt
      the store.
    * Per-tree matrix rebuild is NOT thread-safe.  The single-writer
      invariant is maintained by ``PageIndexToolkit._persist()`` which
      calls ``mark_dirty()`` only after the tree JSON is saved.

## Methods

- `def content_key(model_id: str, title: str, summary: str) -> str` — Compute the SHA-1 content-addressed cache key.
- `def get_or_embed(self, tree_name: str, node_id: str, title: str, summary: str) -> Optional[np.ndarray]` — Return the cached embedding vector for a node, or None if missing.
- `def build_tree_matrix(self, tree_name: str, nodes: list[dict], embed_fn: Callable[[list[str]], np.ndarray]) -> tuple[np.ndarray, list[str]]` — Build (or rebuild) the per-tree ``(N, d)`` embedding matrix.
- `def load_tree_matrix(self, tree_name: str) -> Optional[tuple[np.ndarray, list[str]]]` — Load the materialized per-tree matrix (memory-mapped read-only).
- `def invalidate_tree(self, tree_name: str) -> None` — Delete the per-tree matrix without touching global-tier entries.
