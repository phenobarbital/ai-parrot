---
type: Concept
title: embedding_tree_walk()
id: func:parrot.knowledge.pageindex.vector_walk.embedding_tree_walk
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Beam search over per-node embeddings to propose candidate node_ids.
---

# embedding_tree_walk

```python
async def embedding_tree_walk(tree: dict, query_vec: np.ndarray, store: 'NodeEmbeddingStore', beam_width: int=3, max_depth: int=10, embed_fn=None) -> list[str]
```

Beam search over per-node embeddings to propose candidate node_ids.

At each level, cosine-scores the children of surviving branches, keeps
the top ``beam_width`` candidates, and descends into their subtrees.
Both branch and leaf node_ids are collected as candidates.

The walk is ``async`` so it can be awaited inside async search methods;
current implementation is purely synchronous numpy.

Args:
    tree: PageIndex tree dict (``{"doc_name": str, "structure": [...]}}``).
    query_vec: 1-D float32 query embedding produced by the caller.
    store: :class:`NodeEmbeddingStore` instance.
    beam_width: Number of top candidates to keep at each level.
    max_depth: Maximum descent depth (prevents infinite loops on cycles).
    embed_fn: Callable ``(list[str]) -> np.ndarray`` used to embed node
        texts when their vectors are not already in the store.  When
        ``None``, nodes missing from the store are skipped.

Returns:
    List of ``node_id`` strings in beam-descent order (higher-ranked
    nodes appear first).  May be empty if no embeddings are available.
