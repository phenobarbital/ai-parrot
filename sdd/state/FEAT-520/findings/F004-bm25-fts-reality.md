# F004 — BM25/FTS reality: no BM25 over Postgres anywhere; the "existing seam" is bm25s/FTS5/RRF patterns
**Query**: Q003/Q008 | **Confidence**: high

- Postgres FTS today = ONE artifact: GIN index `to_tsvector('english', metadata->>'searchable_content')` (stores/postgres.py:1488) — **hardcoded English**, no ts_rank query path found.
- Real BM25 implementations: `knowledge/pageindex/hybrid_search.py` (`bm25s` lib + `_rrf_fuse` with `_RRF_K=60` + optional cross-encoder rerank — the RRF+rerank pattern D6 describes, but in Python over one tree); wiki SQLite FTS5; graphindex `persist_sqlite.py` `nodes_fts` FTS5/BM25; `knowledge/retrieval/policies/vector_seed.py` `VectorSeedPolicy` (FTS5 ∥ FAISS, RRF, TASK-2281).
⇒ D6's "BM25 seam existente sobre pgvector" must be BUILT (tsvector/ts_rank_cd or pg_search), not reused. What IS reusable: the RRF pattern and the reranker seam.
