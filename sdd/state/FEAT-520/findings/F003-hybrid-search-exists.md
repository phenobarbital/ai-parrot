# F003 — hybrid_search ALREADY EXISTS on the vector stores; PgVectorStore is SQLAlchemy, not asyncpg
**Query**: Q008/Q010/Q011 | **Confidence**: high

- `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py:1728` — `PgVectorStore.hybrid_search(query, query_tokens, table, schema, top_k, dense_weight=0.7, colbert_weight=0.3, metadata_filters, **kwargs)`. Two-leg only: dense `similarity_search` + `colbert_search`, min-max normalized weighted merge in `_combine_search_results` (:1797) — Python-side, NOT RRF, NOT one-pass SQL, no BM25, no graph leg.
- `stores/arango.py:801` also defines `hybrid_search`.
- `PgVectorStore` imports: `sqlalchemy`, `sqlalchemy.ext.asyncio`, `pgvector.sqlalchemy.Vector`, `default_sqlalchemy_pg` (postgres.py:5-38). **The vector-store layer is SQLAlchemy-based** — the brainstorm's "asyncpg estándar (no SQLAlchemy)" holds for core modules but NOT here.
- asyncpg IS used elsewhere in core: `parrot/core/hooks/postgres.py`, `parrot/eval/sink.py`, `parrot/knowledge/retrieval/pin.py`, `parrot/knowledge/ontology/concept_catalog/seed.py` — precedent for an asyncpg graphindex backend exists.

⇒ Brainstorm §1 "No existe hybrid_search()" is FALSE at the vector-store layer, TRUE for graph/wiki store contracts. Naming collision risk: a new `hybrid_search` on the graph store must not be confused with `PgVectorStore.hybrid_search`.
