# TASK-3692: `SQLToolkit`: error-driven read-repair, warm from plane, plane-aware `validate_query` and `generate_query`

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3691
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (toolkit half). When `execute_query` classifies an error as retryable schema drift (`SQLRetryHandler._is_retryable_error`, sql.py:349; strings `column/relation does not exist` in retries.py:56-57) the toolkit re-describes the referenced tables and writes through — the proven-stale read-repair (G4). `_warm_table_cache` prefers the plane over the database; `validate_query`'s message names the plane; `generate_query` adds FK join paths when a plane exists.

---

## Scope

- Add `_repair_from_error(query, err)`; call it in the retry branch right after `handler._is_retryable_error(err)` succeeds.
- `_warm_table_cache`: try `cache_partition.get(...)` first (which now hits the plane) and only introspect on miss.
- `validate_query` message: `not found in schema plane or cache.` when `cache_partition.plane` is set.
- `generate_query`: when `cache_partition.plane` exists, append `plane.neighbors`-derived join paths for `target_tables` to the schema context (FILL IN via `list_tables`/`get_table` only — the reader Protocol has no neighbors; use the FK dicts on the returned `TableMetadata`).
- Write `test_sql_toolkit_plane.py`.

**NOT in scope**: DatabaseAgent wiring (TASK-3693), CachePartition internals (TASK-3691).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | repair hook, warm, validate, generate_query |
| `packages/ai-parrot/tests/bots/database/test_sql_toolkit_plane.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.bots.database.toolkits.sql import SQLToolkit                 # verified: packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:62
from parrot.bots.database.retries import SQLRetryHandler                   # verified: retries.py:123 (already imported at sql.py:24)
from parrot.bots.database.models import TableMetadata, Completeness        # verified: models.py:131, :97
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):                                              # :62
    async def describe_table(self, schema: str, table: str) -> Optional[TableMetadata]   # :183 (cache first, FULL on miss, stores via cache_partition.store_table_metadata)
    async def generate_query(self, natural_language, target_tables=None, query_type="SELECT") -> str   # :214
    async def execute_query(...)                                                # :283
            handler = SQLRetryHandler(toolkit=self, config=retry_cfg)          # :349 ← anchor
            if not handler._is_retryable_error(err): raise                     # :350-351
            table, column = handler._extract_table_column_from_error(query, err)   # :353
    async def validate_query(self, sql) -> Dict[str, Any]                       # :509; from_pattern regex :522; "not found in cache." :534 ← anchor
    async def _warm_table_cache(self) -> None                                   # :576 ← anchor (loops self.tables, describe_table each)
# TASK-3691: self.cache_partition.plane (SchemaPlaneReader | None), .plane_write, .origin; CachePartition.get(schema, table, required=, max_age=) now consults the plane
# packages/ai-parrot/src/parrot/bots/database/retries.py:56-57 "column does not exist", "relation does not exist" in retry_on_errors
```

### Does NOT Exist
- ~~a `neighbors` method on `SchemaPlaneReader`~~ — the Protocol has get_table/put_table/list_tables only; build join paths from `TableMetadata.foreign_keys`
- ~~`SQLToolkit.plane`~~ — the plane hangs off `self.cache_partition` (TASK-3691), not the toolkit
- ~~a full `information_schema` scan on the request path~~ — forbidden (G4): repair only the tables referenced by the failing query

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/database/test_sql_toolkit_plane.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#SQLToolkit",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#SQLToolkit.execute_query",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#SQLToolkit.validate_query",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#SQLToolkit._warm_table_cache",
    "sym:packages/ai-parrot/src/parrot/bots/database/retries.py#SQLRetryHandler"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
sql.py:349-362 (retry branch) and :509-540 (table-reference regex to reuse for repair targets).

### Key Constraints
- Repair never raises and never runs when `cache_partition` is None or has no plane.
- Repair targets = tables referenced by the failing query (reuse the `validate_query` regex), max 10.
- Existing `test_sql_toolkit_methods.py` / `test_retry_wiring.py` stay green.

### References in Codebase
- packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:283-362, :509-540, :576-635
- packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:431 — read-repair shape (stale flag, partial repair)

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Add `_repair_from_error` and call it after :351 — why: a proven-stale signal is the only request-path trigger allowed (G4/AC9).
2. Change `_warm_table_cache` to call `cache_partition.get` before `describe_table` — why: warm from the plane, not the database.
3. Adjust the `validate_query` message when a plane exists — why: 'not found in plane' is a stronger statement (spec §2).
4. Extend `generate_query` context with FK join paths — why: text-to-SQL's biggest win.
5. Tests with a fake partition/plane.

### `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            handler = SQLRetryHandler(toolkit=self, config=retry_cfg)' packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py) → sql.py:349
# AFTER — insert below the two lines that follow it (`if not handler._is_retryable_error(err): raise`, :350-351):
            await self._repair_from_error(query, err)  # FEAT-600: proven-stale read-repair, never raises

# NEW METHOD — add next to validate_query (after :540):
    async def _repair_from_error(self, query: str, err: Exception) -> None:
        """On a retryable schema error, re-describe the tables the failing query references and write them through
        to the schema plane (FEAT-600 AC9). No-op without a plane; never raises."""
        import re

        part = self.cache_partition
        if part is None or getattr(part, "plane", None) is None:
            return
        refs = re.findall(r'(?:FROM|JOIN)\s+(?:"?(\w+)"?\.)?"?(\w+)"?', query, re.IGNORECASE)  # same regex as validate_query :522
        for schema_part, table in refs[:10]:
            try:
                meta = await self._introspect_table(schema_part or self.primary_schema, table)  # FILL IN: name of the FULL-introspection helper describe_table calls on a miss (read sql.py:183-213)
                if meta is not None:
                    await part.store_table_metadata(meta)  # write-through happens inside (TASK-3691)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("schema read-repair failed for %s: %s", table, exc)

# occurrences: 1 (verified: grep -c "                    errors.append(f\"Table '{schema}.{table_part}' not found in cache.\")" …/sql.py) → sql.py:534
# REPLACE that line with:
                    where = "schema plane or cache" if getattr(self.cache_partition, "plane", None) is not None else "cache"
                    errors.append(f"Table '{schema}.{table_part}' not found in {where}.")

# occurrences: 1 (verified: grep -c '    async def _warm_table_cache(self) -> None:' …/sql.py) → sql.py:576
# INSIDE the per-table loop body, BEFORE the existing describe_table/introspection call:
            if self.cache_partition is not None:
                cached = await self.cache_partition.get(schema, table, required=Completeness.FULL)  # plane tier included (TASK-3691)
                if cached is not None:
                    continue  # FEAT-600: warmed from the plane, no database round-trip
# generate_query (:214): FILL IN — when getattr(self.cache_partition, "plane", None): for each target table, get(...) and append
#   "JOIN PATHS: a.b.col -> c.d.col" lines built from TableMetadata.foreign_keys to the schema context string — bounded by ≤ 20 lines
```
**Why**: Repair is keyed on the same classification the retry handler already trusts (retries.py:56-57) and touches only referenced tables (G4). Warm-from-plane goes through `CachePartition.get` so the tier order is owned by one place.

### FILL IN checklist
- [ ] name of the FULL introspection helper used by `describe_table` on a miss (read sql.py:183-213)
- [ ] `generate_query` join-path lines — ≤ 20
- [ ] tests: simulated `relation does not exist` → helper called for `epson.sales` and plane `puts` non-empty; no plane → no call; warm skips DB for plane-present tables; validate message toggles

---

## Acceptance Criteria

- [ ] retryable schema error → referenced tables re-described and written through (AC9); with no plane nothing extra happens
- [ ] `_warm_table_cache` never calls the database for tables the plane serves
- [ ] `validate_query` message names the plane only when one is set
- [ ] `pytest packages/ai-parrot/tests/bots/database/test_sql_toolkit_methods.py packages/ai-parrot/tests/bots/database/test_retry_wiring.py -q` green
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/database/test_sql_toolkit_plane.py -q`
- `pytest packages/ai-parrot/tests/bots/database/test_sql_toolkit_methods.py -q`
- `pytest packages/ai-parrot/tests/bots/database/test_retry_wiring.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_sql_toolkit_plane.py
import pytest
from parrot.bots.database.toolkits.sql import SQLToolkit

async def test_validate_message_names_plane(monkeypatch):
    tk = SQLToolkit(dsn="postgres://x", database_type="postgresql")
    class Part:  # minimal partition double
        plane = object()
        async def get_table_metadata(self, s, t): return None
    tk.cache_partition = Part()
    out = await tk.validate_query("SELECT 1 FROM public.nope")
    assert "schema plane or cache" in out["errors"][0]

async def test_repair_noop_without_plane():
    tk = SQLToolkit(dsn="postgres://x", database_type="postgresql")
    tk.cache_partition = None
    await tk._repair_from_error("SELECT * FROM a.b", RuntimeError("relation does not exist"))  # must not raise
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3691` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: sonnet, backend: native, attempt_uid b7d1fc4b12214f28b4f29996c62f2e52)
**Date**: 2026-09-24
**Notes**: Implementation commit `167407d62` + engine lint-autofix commit `bd3bf02db` (merge `85a5e4653`). `SQLToolkit`: error-driven read-repair (`_repair_from_error`), warm from plane (`_warm_table_cache` consults `cache_partition.get` first), plane-aware `validate_query` (message toggles "schema plane or cache" vs "cache") and `generate_query` (appends bounded "JOIN PATHS:" lines from FK metadata when a plane is present). Coder's own pre-merge run: 32 passed (15 new + 17 parity, `test_sql_toolkit_methods.py` + `test_retry_wiring.py`). Engine-side merge fidelity check passed (`unexpected_files: []`).
**Merge validation**: merge-tier (root scope) — same 4 pre-existing/environmental failures as prior chunks (see `issue:33fe54e65d2d`), unrelated to this task's files. Reviewed via `coder-review:7cd1b3f7350b583a153932dc`, zero fix commits needed.

**Deviations from spec**: none
