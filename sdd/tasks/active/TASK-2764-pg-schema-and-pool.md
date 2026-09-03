# TASK-2764: `pg_schema.py` — graphindex.* DDL, versioned migration, asyncpg pool base

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-520. Everything else in this feature (both stores, the
temporal plane, hybrid retrieval) sits on one shared Postgres schema
`graphindex.*` and one asyncpg connection layer. This task creates that
foundation: the normative DDL from spec §2 "Schema DDL", a versioned
idempotent migration in the house style, pool management, and pgvector codec
registration. **asyncpg is mandatory — zero SQLAlchemy** (spec U4/D8).

---

## Scope

- Implement `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py`:
  - `PG_SCHEMA_VERSION` constant + `graphindex.meta` (or equivalent) version
    stamp table.
  - Full DDL from spec §2: `nodes`, `node_versions` (bitemporal, EXCLUDE
    constraint), `edges` (validity + `evidence_ref` jsonb + confidence CHECK),
    `embeddings` (pgvector), `files` (staleness), `commits` + `commit_items`,
    `symbols` (columns mirroring the wiki SQLite `symbols` table).
  - `ensure_schema(pool)` — idempotent: `CREATE SCHEMA/TABLE IF NOT EXISTS` +
    `_MIGRATION_COLUMNS`-style ALTER-in for post-v1 columns (empty dict now,
    machinery in place), version stamp recorded.
  - `create_pg_pool(dsn, ...)` helper: `asyncpg.create_pool` with an `init`
    callback that registers the pgvector codec
    (`pgvector.asyncpg.register_vector`) and sets `search_path` to the
    configured schema.
  - navconfig-backed settings: `GRAPHINDEX_PG_DSN`, `GRAPHINDEX_PG_SCHEMA`
    (default `graphindex`), `GRAPHINDEX_EMBEDDING_DIM`,
    `GRAPHINDEX_FTS_REGCONFIG` (namespace-prefix → regconfig map, e.g.
    `{"legal:": "spanish", "sym:": "simple"}`) with a
    `resolve_regconfig(namespace) -> str` helper (default `simple`).
  - Required extensions: emit `CREATE EXTENSION IF NOT EXISTS vector` and
    `btree_gist`; fail with a clear error message when the server lacks them.
- Write live-DB-gated tests (skip without `GRAPHINDEX_PG_DSN`).

**NOT in scope**: any store method (TASK-2765+), ANN index creation policy
(TASK-2769 decides HNSW/IVFFlat with spike data — this task only leaves the
embeddings table indexable), wiki store (TASK-2768).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py` | CREATE | DDL + migration + pool + config |
| `packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema.py` | CREATE | live-gated migration/pool tests |
| `pyproject.toml` (ai-parrot package) | MODIFY | optional extra with `asyncpg` + `pgvector` pip deps |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncpg                          # precedent: parrot/core/hooks/postgres.py, parrot/eval/sink.py
from pgvector.asyncpg import register_vector  # pgvector pip pkg — VERIFY installed version exposes it
from navconfig import config            # house config pattern (see parrot/conf.py usage)
```

### Existing Signatures to Use (patterns, same repo)
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "2"                    # :49  — version-stamp pattern
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]]   # :166 — ALTER-in migration pattern
# async def _migrate(self, conn) at :1041 — apply missing columns idempotently

# packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py
_SCHEMA_SQL   # :38 — sibling DDL shape: nodes(:48), edges(:65), files(:41),
              # graph_commits(:82), graph_commit_items(:96)
_MIGRATION_COLUMNS  # :109
```

### Normative DDL
Copy the `CREATE SCHEMA/TABLE` block from spec §2 "Schema DDL (normative
draft)" verbatim as the starting point — key invariants that MUST survive:
- `node_versions`: `EXCLUDE USING gist (concept_id WITH =, validity WITH &&)`;
  partial index `WHERE upper_inf(validity)`; `fts tsvector` (populated by the
  stores at upsert, NEVER a generated column — regconfig is per-row).
- `edges`: `CHECK ((provenance = 'inferred') = (confidence IS NOT NULL))`
  (mirrors `graphindex/schema.py:217-229` validator); `evidence_ref jsonb`.
- `commits.seq bigint GENERATED ALWAYS AS IDENTITY` (revert-conflict ordering).

### Does NOT Exist
- ~~`parrot/knowledge/graphindex/pg_schema.py`~~ — this task creates it.
- ~~SQLAlchemy anywhere in this backend~~ — forbidden (grep-verified AC in spec §5).
- ~~`parrot.stores.postgres` imports~~ — `PgVectorStore` is EXCLUDED (spec U4).
- ~~a shared "postgres pool" utility in core~~ — `core/hooks/postgres.py` and
  `eval/sink.py` each manage their own pool; there is no common helper to
  import. This task creates the graphindex-local one.

---

## Implementation Notes

### Key Constraints
- asyncpg parameterized statements (`$1`), `async with pool.acquire()`.
- Idempotent: `ensure_schema` runs on every store init; second run is a no-op.
- Per-test isolation: tests create a throwaway schema name and
  `DROP SCHEMA ... CASCADE` on teardown (spec §4 fixtures).
- Google docstrings, strict typing, `logging.getLogger(__name__)`.

### References in Codebase
- `parrot/knowledge/wiki/store.py:820-1063` — connect + migrate lifecycle shape.
- `parrot/eval/sink.py` — asyncpg pool usage precedent in core.

---

## Acceptance Criteria

- [ ] `ensure_schema` twice → identical schema, version stamped (test).
- [ ] EXCLUDE constraint active: overlapping `(concept_id, validity)` insert
      raises `asyncpg.exceptions.ExclusionViolationError` (test).
- [ ] edges CHECK enforces confidence ⇔ inferred (test).
- [ ] Pool init registers the vector codec; a `vector` roundtrip works (test).
- [ ] `resolve_regconfig("legal:core") == "spanish"` with the mapped config;
      unmapped → `"simple"` (test).
- [ ] Zero SQLAlchemy imports: `grep -i sqlalchemy pg_schema.py` empty.
- [ ] `ruff check` clean; tests skip cleanly without `GRAPHINDEX_PG_DSN`.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema.py
import os, pytest
pytestmark = pytest.mark.skipif(not os.environ.get("GRAPHINDEX_PG_DSN"),
                                reason="needs live Postgres")

async def test_migration_idempotent(pg_pool, tmp_schema): ...
async def test_exclusion_constraint_rejects_overlap(pg_pool, tmp_schema): ...
async def test_edge_confidence_check(pg_pool, tmp_schema): ...
async def test_vector_codec_roundtrip(pg_pool, tmp_schema): ...
def test_resolve_regconfig_mapping(): ...
```

---

## Agent Instructions

1. Read the spec §2 (DDL) and §7 (patterns/config) first.
2. Verify the Codebase Contract references before writing code.
3. Update the per-spec index status → in-progress / done.
4. Move this file to `sdd/tasks/completed/` on completion and fill the note.

---

## Completion Note

*(Agent fills this in when done)*
