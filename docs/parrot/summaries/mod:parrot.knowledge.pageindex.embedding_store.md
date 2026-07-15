---
type: Wiki Summary
title: parrot.knowledge.pageindex.embedding_store
id: mod:parrot.knowledge.pageindex.embedding_store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Two-tier content-addressed embedding store for PageIndex trees.
relates_to:
- concept: class:parrot.knowledge.pageindex.embedding_store.NodeEmbeddingStore
  rel: defines
---

# `parrot.knowledge.pageindex.embedding_store`

Two-tier content-addressed embedding store for PageIndex trees.

Each PageIndex node's embedding is identified by a content-addressed SHA-1 key
derived from the model identifier, node title, and node summary. This design
survives ``reindex_node_ids`` mutations that rewrite all node_ids on every tree
mutation.

Storage layout::

    <storage_dir>/
        <tree_name>/
            embeddings/
                global/           <- content-addressed .npy sidecar files
                    <sha1_hex>.npy
                <tree_name>.matrix.npy     <- per-tree (N, d) matrix
                <tree_name>.node_order.json <- node_id ordering for the matrix

The global tier caches individual node embeddings keyed by content hash.
The per-tree tier materializes a contiguous ``(N, d)`` float32 numpy array
for fast BLAS matmul — rebuilt via ``build_tree_matrix()``, loaded
(memory-mapped) via ``load_tree_matrix()``, deleted via ``invalidate_tree()``.

An in-memory LRU cache fronts the global tier to avoid repeated disk I/O for
hot nodes across multiple search calls.

## Classes

- **`NodeEmbeddingStore`** — Two-tier content-addressed embedding cache for PageIndex trees.
