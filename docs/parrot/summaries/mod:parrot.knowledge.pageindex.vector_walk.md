---
type: Wiki Summary
title: parrot.knowledge.pageindex.vector_walk
id: mod:parrot.knowledge.pageindex.vector_walk
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Embedding-guided beam walk over a PageIndex tree (Phase B of FEAT-237).
relates_to:
- concept: class:parrot.knowledge.pageindex.vector_walk.FlatMatrixSearch
  rel: defines
- concept: func:parrot.knowledge.pageindex.vector_walk.embedding_tree_walk
  rel: defines
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: references
---

# `parrot.knowledge.pageindex.vector_walk`

Embedding-guided beam walk over a PageIndex tree (Phase B of FEAT-237).

The beam walk descends the tree using local ``(N_children, d) @ (d,)``
cosine-similarity matmuls at each level, keeping the top ``beam_width``
branches.  This is a *proposer* — it produces candidate node_ids that can
be fused with BM25 / LLM-walk rankings via RRF.

Phase B is flag-gated via ``use_embedding_walk`` on
:class:`~parrot.knowledge.pageindex.hybrid_search.HybridPageIndexSearch`.
When the flag is ``False``, the system behaves identically to Phase A.

Design invariant (platform guarantee): the beam walk is deterministic
(pure numpy matmul); the LLM walk / reranker is the final arbiter.

Usage example::

    query_vec = embed_fn(["What is HIPAA?"])[0]
    candidates = await embedding_tree_walk(tree, query_vec, store, beam_width=3)
    # candidates is a list of node_id strings ordered by beam descent

## Classes

- **`FlatMatrixSearch`** — Brute-force cosine similarity search over a node embedding submatrix.

## Functions

- `async def embedding_tree_walk(tree: dict, query_vec: np.ndarray, store: 'NodeEmbeddingStore', beam_width: int=3, max_depth: int=10, embed_fn=None) -> list[str]` — Beam search over per-node embeddings to propose candidate node_ids.
