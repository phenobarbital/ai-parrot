---
type: Wiki Entity
title: HybridPageIndexSearch
id: class:parrot.knowledge.pageindex.hybrid_search.HybridPageIndexSearch
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: BM25 + LLM-walk + dense-cosine hybrid retrieval wrapping a single tree.
---

# HybridPageIndexSearch

Defined in [`parrot.knowledge.pageindex.hybrid_search`](../summaries/mod:parrot.knowledge.pageindex.hybrid_search.md).

```python
class HybridPageIndexSearch
```

BM25 + LLM-walk + dense-cosine hybrid retrieval wrapping a single tree.

Args:
    tree: A PageIndex tree dict (``{doc_name, structure: [...]}``).
    adapter: The LLM adapter used by the inner :class:`PageIndexRetriever`.
    reranker: Optional reranker applied to the fused candidate set.
    model: Model passed through to :class:`PageIndexRetriever`.
    default_bm25_k: Number of candidates fetched from BM25 per query.
    content_loader: Optional per-node content loader for BM25 index.
    embedding_store: Optional :class:`NodeEmbeddingStore` for dense search
        (Phase A of FEAT-237).  When ``None``, ``use_vec=True`` in
        :meth:`search` silently returns empty dense rankings.
    embed_fn: Callable ``(list[str]) -> np.ndarray`` used to embed node
        texts and query strings for dense ranking.  Required when
        ``embedding_store`` is supplied.
    use_vec_rank: Default value of the ``use_vec`` flag in :meth:`search`.
    use_embedding_walk: Reserved for Phase B (beam walk).  Stored but
        unused in this implementation.

## Methods

- `def set_content_loader(self, loader: Optional[Callable[[str], Optional[str]]]) -> None` — Swap the per-node content loader. Marks the BM25 index dirty.
- `def mark_dirty(self) -> None` — Invalidate the BM25 index and embedding matrix.
- `def replace_tree(self, tree: dict[str, Any]) -> None`
- `async def search(self, query: str, top_k: int=10, use_bm25: bool=True, use_llm_walk: bool=True, use_vec: bool=False, use_embedding_walk: Optional[bool]=None, rerank: bool=False) -> list[dict[str, Any]]` — Run hybrid search and return a list of candidate node summaries.
