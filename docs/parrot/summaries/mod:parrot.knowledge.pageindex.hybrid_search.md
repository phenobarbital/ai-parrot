---
type: Wiki Summary
title: parrot.knowledge.pageindex.hybrid_search
id: mod:parrot.knowledge.pageindex.hybrid_search
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Hybrid search over a PageIndex tree.
relates_to:
- concept: class:parrot.knowledge.pageindex.hybrid_search.HybridPageIndexSearch
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.llm_adapter
  rel: references
- concept: mod:parrot.knowledge.pageindex.retriever
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
- concept: mod:parrot.knowledge.pageindex.vector_walk
  rel: references
- concept: mod:parrot.models.stores
  rel: references
---

# `parrot.knowledge.pageindex.hybrid_search`

Hybrid search over a PageIndex tree.

Combines three signals:

* **BM25** lexical search over flattened node text (title + summary + text).
  Backed by the ``bm25s`` library (an optional extra).
* **LLM tree walk** via :class:`PageIndexRetriever` — the existing
  reasoning-based retriever that selects a list of relevant node ids.
* **Dense cosine-similarity** via ``_vec_rank`` over a pre-built node
  embedding matrix (Phase A of FEAT-237, enabled with ``use_vec=True``).
* **Reciprocal Rank Fusion** to combine up to three rankings.

An :class:`AbstractReranker` may optionally be supplied to rerank the
fused candidate set with a cross-encoder.

The BM25 index is rebuilt lazily — every mutation calls ``mark_dirty``,
and the next ``search`` rebuilds before scoring.  The embedding matrix
uses the same dirty / invalidate pattern via :class:`NodeEmbeddingStore`.

## Classes

- **`HybridPageIndexSearch`** — BM25 + LLM-walk + dense-cosine hybrid retrieval wrapping a single tree.
