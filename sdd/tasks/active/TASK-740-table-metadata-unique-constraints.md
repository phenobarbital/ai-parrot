# TASK-740: TableMetadata.unique_constraints + introspection hook

**Feature**: FEAT-106 — NavigatorToolkit ↔ PostgresToolkit Interaction
**Spec**: `sdd/specs/navigatortoolkit-postgrestoolkit-interaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`PostgresToolkit.upsert_row` (TASK-743) wants to default `ON CONFLICT (…)`
to primary keys **or** to any UNIQUE constraint the caller names. Today
`TableMetadata` carries only `primary_keys` — UNIQUE constraints are
implicit in `indexes` and not extracted. This task adds a first-class
`unique_constraints` attribute and a dialect hook that populates it at
table warm-up time.

Implements **Module 2** of the spec.

---

## Scope

- Add `unique_constraints: List[List[str]] = field(default_factory=list)`
  to `TableMetadata` (`models.py` after the `indexes` field around line 116).
  Each inner list is one UNIQUE constraint's column set, in ordinal order.
- Extend `TableMetadata.to_dict()` (if it exists — verify) so the new
  field is serialized alongside `primary_keys`.
- Add a new dialect hook on `SQLToolkit` alongside `_get_primary_keys_query`
  (sql.py near line 424):
  ```python
  def _get_unique_constraints_query(
      self, schema: str, table: str
  ) -> tuple[str, Dict[str, Any]]:
      """Return (SQL, params) for fetching UNIQUE constraints of (schema, table)."""
  ```
  Default body queries `information_schema.table_constraints` JOIN
  `information_schema.key_column_usage` WHERE
  `constraint_type = 'UNIQUE'`, grouped by `constraint_name`, ordered by
  `ordinal_position`.
- Extend `SQLToolkit._build_table_metadata` (sql.py line 545) to:
  1. Execute the new query via `self._execute_asyncdb(sql)` after PKs.
  2. Group rows by `constraint_name`.
  3. Produce `List[List[str]]`; assign to `metadata.unique_constraints`.
  4. Tolerate the query returning zero rows — leave the list empty.
- Optionally override `_get_unique_constraints_query` inside
  `PostgresToolkit` to also include UNIQUE **indexes** (not just named
  constraints) by joining `pg_constraint` + `pg_index`. If the default
  covers everything Navigator needs (it does — all Navigator tables use
  named UNIQUE constraints, no UNIQUE indexes), skip the override.
- Add the unit tests listed below.

**NOT in scope**:
- Consuming `unique_constraints` anywhere — TASK-743 does that in
  `upsert_row` defaulting.
- Refactoring how PKs are extracted — leave `_get_primary_keys_query`
  alone.
- Touching `CachePartition` — it stores `TableMetadata` transparently;
  the new field rides along.
- BigQuery / Influx / ElasticSearch overrides — they already use
  SQLToolkit-style or not-applicable introspection.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/models.py` | MODIFY | Add `unique_constraints` field to `TableMetadata` dataclass + `to_dict` |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | Add `_get_unique_constraints_query`; extend `_build_table_metadata` |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY (optional) | PG-specific override if default misses UNIQUE indexes |
| `tests/unit/test_table_metadata_unique.py` | CREATE | Unit tests for default-empty, hook-populates, serialization |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.database.models import TableMetadata
# verified at: packages/ai-parrot/src/parrot/bots/database/models.py:106

from parrot.bots.database.toolkits.sql import SQLToolkit
# verified at: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:10

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/database/models.py
@dataclass
class TableMetadata:                                            # line 106
    schema: str                                                 # line 108
    tablename: str                                              # line 109
    table_type: str                                             # line 110
    full_name: str                                              # line 111
    comment: Optional[str] = None                               # line 112
    columns: List[Dict[str, Any]] = field(default_factory=list) # line 113
    primary_keys: List[str] = field(default_factory=list)       # line 114
    foreign_keys: List[Dict[str, Any]] = field(default_factory=list)  # line 115
    indexes: List[Dict[str, Any]] = field(default_factory=list) # line 116
    row_count: Optional[int] = None                             # line 117
    sample_data: List[Dict[str, Any]] = field(default_factory=list)  # line 118
    # ADD AFTER line 118 (verify the exact position):
    # unique_constraints: List[List[str]] = field(default_factory=list)
    def to_dict(self) -> Dict[str, Any]: ...                    # around line 140
    # Existing serialization includes: primary_keys — mirror that for unique_constraints
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):
    def _get_primary_keys_query(                                # line 424
        self, schema: str, table: str,
    ) -> tuple[str, Dict[str, Any]]: ...
    # ADD alongside: _get_unique_constraints_query(schema, table) -> tuple[str, Dict]

    async def _execute_asyncdb(                                 # line 451
        self, sql: str, limit: int = 1000, timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]: ...
    # Returns (rows, error_message). Use for running the constraints query.

    async def _build_table_metadata(                            # line 545
        self, schema: str, table: str, table_type: str,
        comment: Optional[str] = None,
    ) -> Optional[TableMetadata]: ...
    # After the PK-extraction block, add the UNIQUE-constraint extraction block.
```

### Does NOT Exist

- ~~`TableMetadata.unique_constraints`~~ — attribute does not exist today.
- ~~`TableMetadata.uniques`~~ — no such short alias; use the full name.
- ~~`SQLToolkit._get_unique_constraints_query`~~ — hook does not exist today.
- ~~`DatabaseToolkit._get_unique_constraints_query`~~ — the base class doesn't own this; it lives on `SQLToolkit`.
- ~~`information_schema.unique_constraints`~~ — not a real view; use `table_constraints WHERE constraint_type = 'UNIQUE'` + `key_column_usage`.
- ~~`CachePartition.has_unique_constraints`~~ — no new cache API needed.

---

## Implementation Notes

### Pattern to Follow

The `_get_primary_keys_query` (sql.py:424) is the model — `_get_unique_constraints_query`
should follow the exact same shape: return `(sql_text, params_dict)`.

```sql
-- Default SQL (adjust to match existing _get_primary_keys_query style)
SELECT
    tc.constraint_name,
    kcu.column_name,
    kcu.ordinal_position
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = tc.constraint_name
 AND kcu.table_schema   = tc.table_schema
 AND kcu.table_name     = tc.table_name
WHERE tc.table_schema = :schema
  AND tc.table_name   = :table
  AND tc.constraint_type = 'UNIQUE'
ORDER BY tc.constraint_name, kcu.ordinal_position;
```

Grouping pattern in Python:

```python
grouped: Dict[str, List[str]] = {}
for row in rows:
    grouped.setdefault(row["constraint_name"], []).append(row["column_name"])
metadata.unique_constraints = list(grouped.values())
```

### Key Constraints

- The new field MUST default to `[]` so every existing `TableMetadata(...)`
  constructor call continues to work without change.
- Populate deterministically: sort the outer list by
  `(first_column_name, constraint_name)` so the same DB always yields
  the same ordering — `upsert_row` relies on this for stable cache keys.
- Use `self._execute_asyncdb(sql)` — not `self.execute_query` (which has
  its own safety layer that flags `SELECT … FROM information_schema`).
- Log at DEBUG — not INFO — when rows are empty; this runs per-table on warm-up.
- Do NOT swallow driver errors: if the query fails, let
  `_build_table_metadata` handle the exception path the same way PK
  extraction does.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` (lines 322–545) — warm-up flow
- `packages/ai-parrot/src/parrot/bots/database/models.py:106-150` — TableMetadata dataclass
- `packages/ai-parrot/src/parrot/bots/database/cache.py` — stores `TableMetadata` verbatim; no change

---

## Acceptance Criteria

- [ ] `TableMetadata(...)` with no `unique_constraints=` kwarg sets `[]` default
- [ ] `TableMetadata.to_dict()` (or equivalent serialization) includes `unique_constraints`
- [ ] `SQLToolkit._get_unique_constraints_query("public", "t")` returns `(str, dict)` — SQL parseable, params non-None
- [ ] `SQLToolkit._build_table_metadata` populates `unique_constraints` on its return value when the hook yields rows (tested with a stubbed `_execute_asyncdb`)
- [ ] Existing tests that construct `TableMetadata` manually still pass unchanged
- [ ] `pytest tests/unit/test_table_metadata_unique.py -v` passes
- [ ] No change to `primary_keys` extraction logic or tests

---

## Test Specification

```python
# tests/unit/test_table_metadata_unique.py
from unittest.mock import AsyncMock, patch
import pytest
from parrot.bots.database.models import TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit


class TestTableMetadataUniqueConstraints:
    def test_default_empty(self):
        meta = TableMetadata(
            schema="test",
            tablename="t",
            table_type="BASE TABLE",
            full_name='"test"."t"',
            columns=[{"name": "id", "type": "integer", "nullable": False, "default": None}],
            primary_keys=["id"],
        )
        assert meta.unique_constraints == []

    def test_to_dict_includes_unique(self):
        meta = TableMetadata(
            schema="test", tablename="t", table_type="BASE TABLE",
            full_name='"test"."t"', primary_keys=["id"],
            unique_constraints=[["email"], ["a", "b"]],
        )
        d = meta.to_dict()
        assert d["unique_constraints"] == [["email"], ["a", "b"]]


class TestSqlToolkitUniqueHook:
    def test_get_unique_constraints_query_shape(self):
        # Instantiate via subclass that exposes the hook — or test at class level.
        sql, params = SQLToolkit._get_unique_constraints_query(
            SQLToolkit, "public", "t"  # adapt to bound/static call style
        )
        assert "UNIQUE" in sql.upper()
        assert "public" in str(params.values()).lower() or "public" in sql

    @pytest.mark.asyncio
    async def test_build_table_metadata_populates_unique(self, monkeypatch):
        # Stub _execute_asyncdb to return UNIQUE rows on second call.
        # Verify metadata.unique_constraints reflects the parsed groups.
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `TableMetadata` field list matches (line numbers may drift); confirm `_build_table_metadata` still exists at/near sql.py:545
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** per scope — prefer the default hook; only add a PG override if the default misses Navigator UNIQUE constraints (verify against `auth.programs` UNIQUE `(program_slug)` etc.)
6. **Verify** all acceptance criteria
7. **Move this file** to `tasks/completed/TASK-740-table-metadata-unique-constraints.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
