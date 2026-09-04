# F001 — GraphIndex has its OWN persistence seam, separate from BaseWikiStore
**Query**: Q001/Q014 (wiki_query + tree) | **Confidence**: high

GraphIndex persistence is NOT BaseWikiStore. Two mirrored backends exist:
- `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` — `GraphIndexPersistence(graph_store: OntologyGraphStore)` → ArangoDB + pgvector embeddings. Public API: `persist_graph(ctx, nodes, edges)`, `replace_document_slice(ctx, document_uri, nodes, edges)`, `load_graph(ctx)`, plus the **graph commit protocol**: `apply_update(ctx, GraphUpdate) -> CommitReceipt`, `get_commit`, `list_commits`, `revert_commit` (collections `gi_commits`/`gi_commit_items`, per-tenant asyncio.Lock, seq-ordered revert-conflict detection).
- `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` — `SQLitePersistence` (FEAT-240), aiosqlite, WAL, `files` staleness table, `nodes_fts` FTS5/BM25 virtual table. Docstring: "Public API mirrors GraphIndexPersistence".
- `factory.py:33,239` instantiates `SQLitePersistence(Path(db_dir))` + `GraphPublisher(persistence, ctx)`; Arango path via `arango_db=f"db_{tenant_id}"`.

⇒ OQ1 evidence: a Postgres backend for GraphIndex = a third `persist_postgres.py` implementing this mirrored API (incl. commit protocol), NOT a BaseWikiStore impl. Wiki and graphindex are distinct planes with distinct contracts.
