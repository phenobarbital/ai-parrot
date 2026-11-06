# TASK-5256: PostgreSQL schema for the vocabulary store (`pg_schema.py`)

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5254, TASK-5255
**Assigned-to**: unassigned

---

## Context

Spec Module 4. Idempotent DDL of spec §2 (lines 448–521) in schema `ontology_store` (configurable,
validated), extension checks for `vector` and `pg_trgm`, the ANN index over current concept rows,
and an asyncpg pool with the pgvector codec. Follows FEAT-520's `graphindex/pg_schema.py` but
**must not import it** (FEAT-541 will move that tree to another distribution; spec §7).

---

## Scope

- `vocabulary/pg_schema.py` with `ONTOLOGY_PG_SCHEMA_VERSION`, `validate_schema_name`, `_ddl`,
  `ensure_schema`, `create_ontology_pg_pool` (signatures fixed by spec lines 747–760), plus private
  `_ensure_extensions`.
- `ensure_schema` creates extensions, the schema, all tables and non-ANN indexes of spec §2, then
  the ANN index (`hnsw` or `ivfflat`, from `ONTOLOGY_ANN_INDEX_KIND`) on `concept.embedding`
  `WHERE until_version IS NULL`, all inside one transaction after the extension step.
- `test_pg_schema.py` — unit (no DB) + integration (live DB, skip-gated).

**NOT in scope**: writing rows (TASK-5260); touching the existing `ontology` schema or the
`ontology_concept*` tables — forbidden (spec AC Phase 2 #1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/pg_schema.py` | CREATE | DDL, extensions, pool |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_pg_schema.py` | CREATE | unit + integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncpg                                         # installed 0.32.0 — import at module level is OK here (not the package root)
from pgvector.asyncpg import register_vector           # installed pgvector 0.4.1; used at graphindex/pg_schema.py:521
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings   # TASK-5254
```

### Existing Signatures to Use
```python
# TASK-5254 — parrot/knowledge/ontology/vocabulary/settings.py
def resolve_ontology_settings(*, backend=None, dsn=None, schema=None) -> OntologyStoreSettings
    # .dsn, .schema_name (default "ontology_store"), .embedding_dim (1024), .ann_index_kind ("hnsw")

# PATTERN ONLY — parrot/knowledge/graphindex/pg_schema.py (do not import)
#   :356 _ensure_extensions(conn): CREATE EXTENSION IF NOT EXISTS per ext; RuntimeError with an actionable message
#   :401 ensure_schema: validate → _ensure_extensions → transaction(execute DDL) → logger.info
#   :521-547 create_pg_pool: bootstrap asyncpg.connect + _ensure_extensions BEFORE create_pool (eager
#            min_size=1 connection would otherwise fail register_vector on a fresh server),
#            then init=_init: register_vector(conn); SET search_path

# TASK-5255 conftest fixtures: pg_pool (plain asyncpg pool, skips without DSN), pg_schema_name (unique, dropped)
```

### Does NOT Exist
- ~~`ontology_store` schema~~ — created here; the name `ontology` is **taken** (pgvector `ontology.concepts`).
- ~~DDL for `ontology_concept*`~~ — never add it.
- ~~`from parrot.knowledge.graphindex import pg_schema`~~ — forbidden import (spec §7 "Sequencing").

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/pg_schema.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_pg_schema.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Copy the spec §2 DDL into `_ddl` with `{s}`/`{dim}` substitution — *why*: the DDL is fixed by the spec.
2. Write `_ensure_extensions` and `ensure_schema` — *why*: idempotent, actionable errors (FEAT-520 convention).
3. Write `create_ontology_pg_pool` with the bootstrap-before-pool order — *why*: pattern note above.
4. Tests.

### `.../vocabulary/pg_schema.py` (CREATE)
```python
"""PostgreSQL schema of the ontology vocabulary store (FEAT-824).

Idempotent DDL in a dedicated schema (default ``ontology_store``). Does not import
``parrot.knowledge.graphindex``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg

from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.pg_schema")

ONTOLOGY_PG_SCHEMA_VERSION = "1"
_REQUIRED_EXTENSIONS = ("vector", "pg_trgm")
_VALID_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_schema_name(schema: str) -> None:
    """Raise ValueError unless ``schema`` is a plain, unquoted SQL identifier."""
    if not _VALID_SCHEMA_NAME.match(schema):
        raise ValueError(f"Invalid ontology schema name {schema!r} — expected ^[a-z_][a-z0-9_]*$")


def _ddl(schema: str, embedding_dim: int) -> str:
    """Full idempotent DDL (tables and non-ANN indexes) for the vocabulary schema."""
    s, dim = schema, int(embedding_dim)
    # FILL IN: return f"CREATE SCHEMA IF NOT EXISTS {s};" + the spec §2 DDL (lines 449-517) with
    #          {s}/{dim} substituted — verbatim tables, CHECKs, FKs, partial unique indexes, trgm/btree indexes.
    raise NotImplementedError


async def _ensure_extensions(conn: asyncpg.Connection) -> None:
    """CREATE EXTENSION IF NOT EXISTS vector / pg_trgm; RuntimeError with an actionable message on failure."""
    # FILL IN: mirror graphindex/pg_schema.py:356-380 (privilege / not-available message naming the extension).
    raise NotImplementedError


async def ensure_schema(pool: asyncpg.Pool, schema: str | None = None, *,
                        embedding_dim: int | None = None, ann_index_kind: str | None = None) -> None:
    """Create extensions, schema, tables and indexes if missing.

    Raises:
        ValueError: unsafe schema name or unknown ANN kind.
        RuntimeError: an extension cannot be created.
    """
    settings = resolve_ontology_settings(schema=schema)
    schema = settings.schema_name
    validate_schema_name(schema)
    # FILL IN: dim/kind default from settings; acquire; _ensure_extensions; in one transaction execute
    #          _ddl(schema, dim) and the ANN index:
    #          CREATE INDEX IF NOT EXISTS concept_embedding_ann ON {schema}.concept USING <hnsw|ivfflat>
    #          (embedding vector_cosine_ops) [WITH (lists = 100) for ivfflat] WHERE until_version IS NULL;
    #          logger.info naming schema + ONTOLOGY_PG_SCHEMA_VERSION.
    raise NotImplementedError


async def create_ontology_pg_pool(dsn: str | None = None, *, schema: str | None = None,
                                  min_size: int = 1, max_size: int = 10, **kwargs: Any) -> asyncpg.Pool:
    """asyncpg pool with the pgvector codec registered on every connection.

    Raises:
        ValueError: when no DSN is given and ONTOLOGY_PG_DSN is unset.
    """
    from pgvector.asyncpg import register_vector

    settings = resolve_ontology_settings(dsn=dsn, schema=schema)
    # FILL IN: ValueError when settings.dsn is falsy; bootstrap connect + _ensure_extensions + close;
    #          _init registers the codec (do NOT set search_path — every query schema-qualifies);
    #          return await asyncpg.create_pool(...).
    raise NotImplementedError
```
**Why this shape**: signatures from spec Module 4; queries in later tasks always write
`{schema}.table`, so the pool does not change `search_path` (unlike FEAT-520).

### `.../vocabulary/test_pg_schema.py` (CREATE) — required cases
```python
def test_ddl_is_idempotent_text(): ...          # every CREATE in _ddl("s", 8) is "IF NOT EXISTS"; "{dim}" → vector(8)
def test_schema_name_validated(): ...           # validate_schema_name("ontology-store") raises ValueError
async def test_ensure_schema_twice(pg_pool, pg_schema_name): ...
    # ensure_schema twice on a live server; all 9 tables exist in pg_schema_name;
    # no table was created in schema "ontology" by this call (compare information_schema before/after).
```

### FILL IN checklist
- [ ] `_ddl` body (verbatim spec DDL).
- [ ] `_ensure_extensions`, `ensure_schema`, `create_ontology_pg_pool` bodies.
- [ ] test bodies.

---

## Acceptance Criteria

- [ ] `ensure_schema` is idempotent on a live server and creates every spec §2 table in the target schema.
- [ ] Nothing in schema `ontology` and no `ontology_concept*` table is created or altered.
- [ ] Unsafe schema names are rejected before any SQL runs.
- [ ] `ruff check` passes; no SQLAlchemy.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_pg_schema.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5254 and TASK-5255 are `done`.
2. Verify the Codebase Contract; mark `in-progress`; implement from the blueprint.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (set `ONTOLOGY_PG_DSN` to a
   scratch database to run the integration case; it skips otherwise — say which in the note).
4. Commit only the listed files; close with `parrot sdd task close TASK-5256 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
