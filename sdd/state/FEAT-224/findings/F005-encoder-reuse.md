---
id: F005
query_id: Q005
type: grep
intent: Find an existing encoder/embeddings abstraction to reuse (zero new runtime dep).
executed_at: 2026-06-05T13:09:30Z
duration_ms: 160
parent_id: null
depth: 0
---

# F005 — `SentenceTransformer` already vendored; encoder abstraction present

## Summary

`sentence-transformers` is already a present runtime dependency: it is
instantiated directly in at least three places
(`memory/episodic/embedding.py:64`, `skills/store.py:201`,
`bots/flows/core/storage/mixin.py:45`), each lazily importing `_st`. There is
also an `EmbeddingModel(ABC)` abstraction (`embeddings/base.py:15`) with async
`embed_documents` / `embed_query`. So Axis B1 ("roll-your-own embeddings, zero
new dependency") is fully supported — the e5 multilingual model can be loaded
via the existing `SentenceTransformer` pattern with no new pin.

## Citations

- path: `parrot/memory/episodic/embedding.py`
  lines: 64
  symbol: lazy SentenceTransformer load
  excerpt: |
    self._model = _st.SentenceTransformer(...)

- path: `parrot/skills/store.py`
  lines: 201
  symbol: SentenceTransformer load
  excerpt: |
    self._embedding_model = SentenceTransformer(self._embedding_model_name)

- path: `parrot/embeddings/base.py`
  lines: 15, 169-188
  symbol: `EmbeddingModel`
  excerpt: |
    class EmbeddingModel(ABC): ...
    async def embed_documents(...); async def embed_query(...)

## Notes

Existing code lazy-imports `sentence_transformers as _st` to keep import time
low — the router engine should follow the same lazy pattern. e5 models require
the "query:"/"passage:" prefix convention; document this in the spec.
