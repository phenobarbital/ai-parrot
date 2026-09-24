# TASK-3683: Live producer: introspect a declared source through the SQLToolkit dialect hooks

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3680, TASK-3681
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (producer half). `producers/live.py` picks the dialect toolkit (`PostgresToolkit` for pg_catalog, `BigQueryToolkit`, else `SQLToolkit`) from a `SchemaSourceConfig` + resolved DSN and calls `describe_table` (FULL) per allowed table, emitting `TableRecord`s. Partial failure never raises.

---

## Scope

- Create `schema/producers/live.py` with `toolkit_for` and `introspect` (the `producers/__init__.py` marker comes from TASK-3680).
- Write `test_live_producer.py` with a fake toolkit (no database).

**NOT in scope**: Writing to the plane (TASK-3684), DDL (TASK-3685), CLI (TASK-3687), DSN resolution from navconfig (the caller passes the DSN string).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/live.py` | CREATE | live producer |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_live_producer.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.bots.database.toolkits.sql import SQLToolkit, _SQLGLOT_DIALECT_MAP   # verified: packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:62, :45
from parrot.bots.database.toolkits.postgres import PostgresToolkit                # verified: toolkits/postgres.py:28
from parrot.bots.database.toolkits.bigquery import BigQueryToolkit                # verified: toolkits/bigquery.py:19
from parrot.bots.database.models import TableMetadata, Completeness               # verified: bots/database/models.py:131, :97
from parrot.knowledge.wiki.schema.models import SchemaSourceConfig, TableRecord   # TASK-3680
from parrot.knowledge.wiki.schema.render import content_hash                      # TASK-3681
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:104-118 — DatabaseToolkit.__init__(self, dsn: str, allowed_schemas=None, primary_schema=None, tables=None,
#     read_only=True, cache_partition=None, retry_config=None, database_type="postgresql", use_pool=False, pool_params=None, **kwargs)
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):                                                 # :62
    async def search_schema(...)                                                   # :113
    async def describe_table(self, schema: str, table: str) -> Optional[TableMetadata]   # :183 — cache first, FULL introspection on miss
    _metadata_source = "information_schema"                                        # :80 (PostgresToolkit: "pg_catalog" postgres.py:41)
# describe_table sets meta.source = self._metadata_source (sql.py:953, :1052)
```

### Does NOT Exist
- ~~asyncdb-level `table_info()` helpers~~ — introspection is the hand-written SQL inside `SQLToolkit`; go through `describe_table`
- ~~`SQLToolkit(config=DatabaseToolkitConfig)`~~ — the constructor takes explicit kwargs (base.py:104-118)
- ~~a `MetadataSource` for BigQuery~~ — `BigQueryToolkit` inherits `information_schema`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/live.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_live_producer.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#SQLToolkit",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#SQLToolkit.describe_table",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py#PostgresToolkit",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/bigquery.py#BigQueryToolkit"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`SQLToolkit._warm_table_cache` (sql.py:576) iterates configured tables and tolerates per-table failures — same loop shape.

### Key Constraints
- Never log or store the DSN; log only the alias.
- `introspected_at` is ISO-8601 UTC.
- `sample_data` is dropped unless `schema.table` is in `cfg.include_samples` (G7).

### References in Codebase
- packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:576-635 — warm loop
- packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:183 — describe_table

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Create `live.py` — why: isolates database access from the service so tests can inject a fake toolkit.
2. Implement `toolkit_for` by dialect — why: pg_catalog vs information_schema differ; the toolkits already encode it.
3. Implement `introspect` with per-table try/except — why: one failing table must not fail the sync (spec edge cases).
4. Tests with a fake toolkit whose `describe_table` returns `sales_metadata` or raises.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/live.py` (CREATE)
```python
"""Live producer — TableRecords from a running database via the SQLToolkit dialect hooks (FEAT-600 M2)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from parrot.bots.database.toolkits.bigquery import BigQueryToolkit  # verified: toolkits/bigquery.py:19
from parrot.bots.database.toolkits.postgres import PostgresToolkit  # verified: toolkits/postgres.py:28
from parrot.bots.database.toolkits.sql import SQLToolkit  # verified: toolkits/sql.py:62
from parrot.knowledge.wiki.schema.models import SchemaSourceConfig, TableRecord
from parrot.knowledge.wiki.schema.render import content_hash

logger = logging.getLogger(__name__)
_TOOLKITS: dict[str, type[SQLToolkit]] = {"postgres": PostgresToolkit, "postgresql": PostgresToolkit, "bigquery": BigQueryToolkit}


def toolkit_for(cfg: SchemaSourceConfig, dsn: str) -> SQLToolkit:
    """PostgresToolkit for postgres/postgresql, BigQueryToolkit for bigquery, else generic SQLToolkit."""
    cls = _TOOLKITS.get(cfg.dialect, SQLToolkit)
    return cls(dsn=dsn, allowed_schemas=list(cfg.allowed_schemas), primary_schema=cfg.allowed_schemas[0],
               tables=cfg.tables, read_only=True, database_type=cfg.dialect)  # verified: base.py:104-118


def _targets(cfg: SchemaSourceConfig, tables: list[str] | None) -> list[tuple[str, str]]:
    """Explicit ``tables`` (schema.table) win; else cfg.tables; else every table of every allowed schema (FILL IN via search_schema)."""
    names = tables or cfg.tables or []
    out: list[tuple[str, str]] = []
    for name in names:
        schema, _, table = name.rpartition(".")
        out.append((schema or cfg.allowed_schemas[0], table))
    return out


async def introspect(cfg: SchemaSourceConfig, dsn: str, *, tables: list[str] | None = None,
                     toolkit: SQLToolkit | None = None) -> tuple[list[TableRecord], dict[str, str]]:
    """describe_table (FULL) per target; returns (records, failed) — partial failure never raises.

    Args:
        cfg: Declared source (alias, dialect, schemas). Never logged with the DSN.
        dsn: Resolved connection string (caller resolves it from ``cfg.dsn_env``).
        tables: Optional ``schema.table`` subset.
        toolkit: Injected toolkit (tests); default ``toolkit_for(cfg, dsn)``.
    """
    tk = toolkit or toolkit_for(cfg, dsn)
    targets = _targets(cfg, tables)
    if not targets:
        # FILL IN: enumerate tables per allowed schema through tk.search_schema (sql.py:113) — bounded by cfg.allowed_schemas only
        pass
    records: list[TableRecord] = []
    failed: dict[str, str] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for schema, table in targets:
        try:
            meta = await tk.describe_table(schema, table)  # verified: sql.py:183
        except Exception as exc:  # noqa: BLE001 — one table must not fail the sync
            failed[f"{schema}.{table}"] = f"{type(exc).__name__}: {exc}"
            logger.warning("schema sync %s: %s.%s failed: %s", cfg.alias, schema, table, exc)
            continue
        if meta is None:
            failed[f"{schema}.{table}"] = "not found"
            continue
        if f"{schema}.{table}" not in cfg.include_samples:
            meta.sample_data = []
        records.append(TableRecord(origin=cfg.alias, dialect=cfg.dialect, metadata=meta, content_hash=content_hash(meta), introspected_at=now))
    return records, failed
```
**Why**: Reuses the existing toolkits (spec 'one record, many producers'); `include_samples` allowlist enforces G7; the loop mirrors `_warm_table_cache`'s tolerance for per-table failures.

### FILL IN checklist
- [ ] `_targets` empty case: enumerate via `search_schema` — bounded by `allowed_schemas`
- [ ] tests: happy path, one raising table → `failed`, sample_data dropped unless allowlisted, `toolkit_for` class choice per dialect

---

## Acceptance Criteria

- [ ] `toolkit_for` returns `PostgresToolkit`/`BigQueryToolkit`/`SQLToolkit` by dialect without connecting
- [ ] `introspect` with a fake toolkit returns one `TableRecord` per table and a `failed` map for the raising one; never raises
- [ ] `sample_data` is empty unless the table is in `include_samples`
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_live_producer.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_live_producer.py
import pytest
from parrot.knowledge.wiki.schema.models import SchemaSourceConfig
from parrot.knowledge.wiki.schema.producers.live import introspect, toolkit_for

class FakeTK:
    def __init__(self, meta, boom=()):
        self.meta, self.boom = meta, set(boom)
    async def describe_table(self, schema, table):
        if table in self.boom: raise RuntimeError("down")
        return self.meta

@pytest.fixture
def cfg(): return SchemaSourceConfig(alias="bigquery", dialect="bigquery", dsn_env="X", allowed_schemas=["epson"], tables=["epson.sales", "epson.broken"])

async def test_partial_failure(cfg, sales_metadata):
    recs, failed = await introspect(cfg, "dsn", toolkit=FakeTK(sales_metadata, boom={"broken"}))
    assert [r.metadata.tablename for r in recs] == ["sales"] and "epson.broken" in failed

def test_toolkit_choice(cfg):
    assert type(toolkit_for(cfg, "bigquery://p")).__name__ == "BigQueryToolkit"
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3680, TASK-3681` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: gpt-5.6-terra, backend: codex, attempt_uid f4e4d29152f44da4bdf967999fb8914a)
**Date**: 2026-09-24
**Notes**: Implementation commit `de37b3f1b` + engine lint-autofix commit `df68a3c76` (merge `10259aeeb`). Live producer: introspects a declared source through the SQLToolkit dialect hooks, folding a `TableMetadata` into `TableRecord`s. Engine-side merge fidelity check passed (`unexpected_files: []`).
**Merge validation**: merge-tier (root scope) 4 failed, 1132 passed, 7 skipped, 20 warnings in 68.45s — same 4 pre-existing/environmental failures as prior chunks (see `issue:33fe54e65d2d`), unrelated to this task's files. Reviewed via `coder-review:0d753e6cb287eda6c90a8083`, zero fix commits needed.

**Deviations from spec**: none
