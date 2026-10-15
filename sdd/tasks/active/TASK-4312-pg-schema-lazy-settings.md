# TASK-4312: pg_schema.py import-clean; Postgres settings resolved at selection

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4311
**Assigned-to**: unassigned

---

## Context

Spec §3 M4. `pg_schema.py:19-23` imports asyncpg, navconfig, pgvector and `parrot.conf` and computes `GRAPHINDEX_PG_DSN` etc. at import. ~25 tests and three modules read those names (persist_postgres.py:88, wiki/postgres_store.py:61, wiki/store.py:2733).

---

## Scope

- Remove the module-level `asyncpg`/`navconfig`/`pgvector`/`parrot.conf` imports (asyncpg → TYPE_CHECKING + function-local; pgvector inside `create_pg_pool`).
- Add `PgSettings` (pydantic) + `resolve_pg_settings(*, dsn=None, schema=None)` using `resolve_setting`; `default_dsn` only when the framework passes it explicitly.
- Keep the public names `GRAPHINDEX_PG_DSN`, `GRAPHINDEX_PG_SCHEMA`, `GRAPHINDEX_EMBEDDING_DIM`, `GRAPHINDEX_ANN_INDEX_KIND` as lazily resolved module attributes (PEP 562) — callers/tests unchanged; replace function-default uses (`schema: str = GRAPHINDEX_PG_SCHEMA`) with a literal `DEFAULT_PG_SCHEMA = "graphindex"` + runtime resolution.
- Missing DSN when a pool is requested fails before network I/O naming the keys.
- Tests: importing pg_schema loads none of asyncpg/navconfig/parrot.conf; lazy names resolve from env; missing DSN error.

**NOT in scope**: Backend registry (TASK-4319).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py` | MODIFY | lazy settings |
| `packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema_import_clean.py` | CREATE | import + settings tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.project import resolve_setting  # TASK-4311 (import inside functions — wiki.project is light)
```

### Existing Signatures to Use
```python
# pg_schema.py: import asyncpg :19; from navconfig import config :20; register_vector :21; from parrot.conf import default_dsn :23
#   GRAPHINDEX_PG_DSN :65; GRAPHINDEX_PG_SCHEMA :68; GRAPHINDEX_EMBEDDING_DIM :71; GRAPHINDEX_FTS_REGCONFIG :75; GRAPHINDEX_ANN_INDEX_KIND :89
#   ensure_schema(pool, schema=GRAPHINDEX_PG_SCHEMA) :343; ensure_ann_index :381; create_pg_pool(dsn=None, *, schema=GRAPHINDEX_PG_SCHEMA, ...) :424
```

### Does NOT Exist
- ~~`resolve_pg_settings` / `PgSettings` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema_import_clean.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py#create_pg_pool",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py#ensure_schema"
  ]
}
```

---

## Implementation Notes

`GRAPHINDEX_FTS_REGCONFIG` is a literal dict — stays eager. Lazy module attributes are resolution, not a deprecation shim: tests and the three callers keep using them.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Move imports function-local — *why*: G1.
2. Add PgSettings/resolve_pg_settings — *why*: resolution at selection.
3. PEP 562 for the four config names — *why*: keep callers.
4. Fix def-time defaults — *why*: they would evaluate the lazy name at import.
5. Tests.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.conf import default_dsn' parrot/knowledge/graphindex/pg_schema.py)
# AFTER/AT — anchor `from parrot.conf import default_dsn` (verified: pg_schema.py:23)
# REMOVE lines 19-23 eager imports; ADD:
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import asyncpg

DEFAULT_PG_SCHEMA = "graphindex"


class PgSettings(BaseModel):
    """Resolved GraphIndex Postgres settings."""

    dsn: str | None
    schema_name: str = DEFAULT_PG_SCHEMA
    embedding_dim: int = 1536
    ann_index_kind: str = "ivfflat"


def resolve_pg_settings(*, dsn: str | None = None, schema: str | None = None) -> PgSettings:
    """Resolve GRAPHINDEX_PG_* through resolve_setting (explicit → env → navconfig → default)."""
    from parrot.knowledge.wiki.project import resolve_setting

    # FILL IN: build PgSettings; validate_schema_name(schema_name)
    raise NotImplementedError


def __getattr__(name: str):
    """Lazy GRAPHINDEX_PG_DSN / _SCHEMA / _EMBEDDING_DIM / _ANN_INDEX_KIND."""
    # FILL IN: map the four names to resolve_pg_settings() fields
    raise AttributeError(name)
# FILL IN: delete the four module-level assignments (:65-89 except GRAPHINDEX_FTS_REGCONFIG);
#          defaults `schema: str = GRAPHINDEX_PG_SCHEMA` -> `schema: str = DEFAULT_PG_SCHEMA`;
#          create_pg_pool imports asyncpg + pgvector.asyncpg.register_vector locally; dsn None -> resolve; still None -> ValueError naming GRAPHINDEX_PG_DSN
```
**Why**: pydantic is already imported by the module (BaseModel via schema?) — FILL IN the import if not.

### `packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema_import_clean.py` (CREATE)
```python
"""pg_schema imports clean; settings lazy (FEAT-540 M4)."""
import pytest


def test_import_clean() -> None:
    # FILL IN: probe 'parrot.knowledge.graphindex.pg_schema'; assert asyncpg/navconfig/parrot.conf absent
    ...


def test_lazy_dsn_from_env(monkeypatch) -> None:
    monkeypatch.setenv("GRAPHINDEX_PG_DSN", "postgres://x")
    from parrot.knowledge.graphindex import pg_schema

    assert pg_schema.GRAPHINDEX_PG_DSN == "postgres://x"

# FILL IN: create_pg_pool with no DSN -> ValueError naming the key, raised before any connect
```
**Why**: Import cost + behaviour.

### FILL IN checklist
- [ ] resolve_pg_settings body
- [ ] module __getattr__
- [ ] def-time default fixes
- [ ] local imports in create_pg_pool
- [ ] tests

---

## Acceptance Criteria

- [ ] importing `pg_schema` loads no asyncpg/navconfig/parrot.conf
- [ ] existing Postgres tests still collect and skip/pass as before
- [ ] missing DSN fails before I/O naming keys

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema_import_clean.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4312 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
