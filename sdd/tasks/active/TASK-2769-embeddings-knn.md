# TASK-2769: In-schema embeddings + KNN path

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2765, TASK-2768
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-520. Per resolved U4, embeddings live in
`graphindex.embeddings` (per-VERSION rows — the temporal filter is a join to
`node_versions.validity`), managed via asyncpg. `PgVectorStore` is explicitly
NOT involved. This gives the hybrid retrieval (TASK-2771) its KNN leg inside
the same transaction snapshot as the graph and FTS legs.

---

## Scope

- Embedding write path on `PostgresPersistence`: an
  `upsert_embeddings(ctx, items)`-style method the graphindex embed stage can
  call — rows keyed `(version_id, model)`, `concept_id` denormalized. Check
  how the embed stage currently hands vectors to persistence
  (`graphindex/embed.py` — read it first) and match that seam.
- `PostgresWikiStore.upsert_embedding(concept_id, vector, model="")` →
  embedding row for the concept's CURRENT version.
- `PostgresWikiStore.search_vector(embedding, limit)` → pgvector KNN
  (`ORDER BY embedding <=> $1`) joined to current versions, returning the
  same stub-dict shape as the other wiki backends (with `score`).
- ANN index management in `pg_schema.py`: `ensure_ann_index(pool, *, kind,
  dim)` — config-driven (`GRAPHINDEX_EMBEDDING_DIM`); index type default
  decided by TASK-2770's spike data (leave `hnsw` as provisional default,
  overridable via config; document).
- Dimension guard: reject vectors whose length ≠ configured dim with a clear
  error.

**NOT in scope**: hybrid fusion SQL (TASK-2771), embedding *generation*
(existing embedder stages), reranking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` | MODIFY | embedding upsert + KNN helpers |
| `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py` | MODIFY | upsert_embedding / search_vector over pgvector |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py` | MODIFY | `ensure_ann_index` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_embeddings_postgres.py` | CREATE | live-gated tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pgvector.asyncpg import register_vector   # codec registered in TASK-2764's pool init
# Vector values pass as list[float]/np arrays through the codec — verify the
# installed pgvector pip version's asyncpg docs before assuming numpy support.
```

### Existing Signatures to Use
```python
# TASK-2764 DDL:
# graphindex.embeddings(concept_id text, version_id bigint REFERENCES node_versions
#   ON DELETE CASCADE, model text DEFAULT '', embedding vector, PRIMARY KEY (version_id, model))

# wiki/store.py:451 — the wiki-side signature to implement:
async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None
# wiki/store.py:469:
async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]
# wiki/store.py:348 — rank_by_cosine(embedding, candidates, limit) — the
#   brute-force fallback shape other backends return (stub dicts + "score").

# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py — READ FIRST:
# how embeddings flow from the embed stage today (UniversalNode.embedding_ref
# is a pointer field on the node, schema.py:149) — match that seam, do not
# invent a new pipeline stage.
```

### Does NOT Exist
- ~~`parrot.stores.postgres.PgVectorStore`~~ involvement — EXCLUDED (U4);
  no imports from `parrot.stores.*` in this backend.
- ~~embeddings on `nodes` or `node_versions` columns~~ — separate table only.
- ~~ANN index type decision here~~ — provisional default + config; final
  choice is TASK-2770's output.

---

## Implementation Notes

### Key Constraints
- KNN queries must join validity: `JOIN node_versions v USING (version_id)
  WHERE upper_inf(v.validity)` for current reads (temporal variant comes in
  TASK-2771 with `validity @> $as_of`).
- `ON CONFLICT (version_id, model) DO UPDATE SET embedding = EXCLUDED.embedding`.
- Deleting/closing a version keeps its embedding row (history) — the CASCADE
  fires only on hard node deletion.

### References in Codebase
- Spec §3 Module 6; OQ3 mitigations (pgvector ≥ 0.8 iterative scans).

---

## Acceptance Criteria

- [ ] Embedding upsert + KNN roundtrip returns nearest-first (test with
      synthetic vectors).
- [ ] `search_vector` returns the wiki stub-dict shape with `score` (test).
- [ ] KNN over current versions excludes closed versions (test).
- [ ] Dimension mismatch → explicit error (test).
- [ ] `ensure_ann_index` idempotent (test).
- [ ] Zero SQLAlchemy; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_embeddings_postgres.py
async def test_upsert_and_knn_roundtrip(pg_persistence, ctx): ...
async def test_knn_excludes_closed_versions(pg_persistence, ctx): ...
async def test_wiki_search_vector_shape(pg_wiki_store): ...
async def test_dimension_guard(pg_persistence, ctx): ...
```

---

## Agent Instructions

1. Read `graphindex/embed.py` and spec §3 Module 6 before coding.
2. Verify contract; update index status; completed + note when done.

---

## Completion Note

*(Agent fills this in when done)*
