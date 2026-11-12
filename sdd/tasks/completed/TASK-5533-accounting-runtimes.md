# TASK-5533: Accounting runtimes — DuckDB engine and semantic executor

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5523, TASK-5531, TASK-5532
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and §2 Overview step 5, AC9/AC10. One `CompiledMetricQuery` runs on two targets: in-memory
frames through the core `DuckDBEngine` (TASK-5523), or a database through the shipped semantic `Executor`
(reused per owner decision U1). Both validate exact aggregates and call the shared `evaluate_rows` (TASK-5532), so
both produce identical `Decimal` results.

---

## Scope

- `runtime/__init__.py` (re-exports `DuckDBRuntime`, `DatabaseRuntime`, `FrameProvider` lazily).
- `runtime/duckdb.py`: `DuckDBRuntime(engine, frame_provider)`; `execute(compiled, model)`.
- `runtime/database.py`: `DatabaseRuntime(executor, *, result_limit)`; `dialect_for`, `execute`,
  `fetch_chart_rows`, `fetch_columns`.
- `tests/accounting/test_runtime.py`: `test_duckdb_runtime_uses_frame_provider`,
  `test_database_runtime_builds_governed_query`, `test_database_runtime_truncation_raises`,
  `test_runtimes_agree`, `test_exact_numeric_types` (frame values out of DECIMAL(38,6) rejected before conversion).

**NOT in scope**: the toolkit that selects a runtime (TASK-5536/5537); end-to-end journals (TASK-5540);
changes to `Executor`, `DatabaseQueryToolkit` or `DuckDBSource` (spec non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/__init__.py` | CREATE | lazy exports |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/duckdb.py` | CREATE | DuckDB runtime |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/database.py` | CREATE | executor runtime |
| `packages/ai-parrot-semantic/tests/accounting/test_runtime.py` | CREATE | runtime tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.duckdb_engine import DuckDBEngine, FrameConversionError, to_arrow   # TASK-5523
from parrot.semantic.execution import ConnectionResolver, Executor        # SL/execution.py:18, :52
from parrot.semantic.models import GovernedQuery                         # SL/models.py:202
from parrot.semantic.errors import SemanticExecutionError                # SL/errors.py:35
from parrot.semantic.accounting.errors import AccountingExecutionError   # TASK-5524
from parrot.semantic.accounting.evaluation import evaluate_rows          # TASK-5532
from parrot.semantic.accounting.models import AccountingModel, CompiledMetricQuery, RuntimeResult   # TASK-5525/5526
```

### Existing Signatures to Use
```python
# SL/execution.py
class ConnectionResolver:                                  # :18
    def resolve(self, connection: str, driver: str) -> dict[str, Any]   # :26 — duckdb ⇒ read_only=True default (:46-48)
class Executor:                                            # :52
    def __init__(self, toolkit: DatabaseQueryToolkit, resolver: ConnectionResolver) -> None   # :55; attrs .toolkit, .resolver
    async def run_with_columns(self, governed: GovernedQuery, *, connection: str
        ) -> tuple[list[dict], int, bool, int, list[str]]  # :60 — (rows, row_count, truncated, duration_ms, columns)
        # truncated = len(all_rows) > governed.limit (:85); never rewrites SQL; raises SemanticExecutionError
# SL/models.py:202 — GovernedQuery(frozen) fields, all required:
#   sql, dialect, driver, tables, rls_applied, masked_columns, limit, subject_digest, members, physical_columns
# CORE/tools/databasequery/toolkit.py:202  def get_source(self, driver: str) -> AbstractDatabaseSource
# CORE/tools/databasequery/base.py
#   :337 sqlglot_dialect: str | None
#   :429 async def get_metadata(self, credentials, tables: list[str] | None = None) -> MetadataResult
#   :446 async def query(self, credentials, sql, params=None) -> QueryResult   # rows: list[dict]
#   MetadataResult.tables: list[TableMeta] (:134); TableMeta.columns: list[ColumnMeta] (:118); ColumnMeta.name/.data_type (:100)
# CORE/tools/databasequery/sources/duckdb.py:72-75 — credentials key "database" (default ":memory:")
# DuckDBEngine (TASK-5523): async execute(sql, *, frames=None, parameters=None) -> pa.Table
# to_arrow(frame, *, decimal_columns=(), allow_float=False) -> pa.Table
```

### Does NOT Exist
- ~~`Decimal(str(value))` repair of float aggregates~~ — forbidden (spec rev 0.3); `evaluate_rows` rejects floats.
- ~~a `LIMIT` added to the compiled SQL~~ — send `compiled.sql` unchanged so it matches `sql_hash`.
- ~~`DuckDBSource` frame registration~~ — it opens one connection per query; frames go through `DuckDBEngine`.
- ~~`parrot.semantic.context.current_pctx()`~~ for subject digests — callers pass `subject_digest`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/duckdb.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/database.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_runtime.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/execution.py#Executor",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/execution.py#ConnectionResolver",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#GovernedQuery",
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/base.py#AbstractDatabaseSource"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `runtime/database.py` and `runtime/duckdb.py` are on the governed side: they may import `parrot.semantic.*`
  and `parrot.interfaces.duckdb_engine`; the compile-path modules must not import them.
- The module is named `duckdb.py` inside `runtime/`; use `from __future__ import annotations` and never write a
  bare `import duckdb` there (it would import itself) — DuckDB is reached only through `DuckDBEngine`.
- DuckDB values: convert the Arrow result with `to_pylist()`; decimal columns arrive as `Decimal`.
- Before `to_arrow`, validate exact frame values (precision/scale) for the amount columns — reject out-of-range
  values as `AccountingExecutionError` (spec numeric contract, `test_exact_numeric_types`).
- `SemanticExecutionError` ⇒ `AccountingExecutionError` (`raise ... from exc`).
- `self.logger`; never log SQL at INFO.

---

## Implementation Blueprint

### Steps (in order)
1. `runtime/__init__.py` with a lazy map (like the package `__init__`).
2. `DuckDBRuntime.execute` — *why*: simplest target, used by the e2e tests.
3. `DatabaseRuntime` with a fake executor in tests — *why*: no live database needed for unit tests.
4. `test_runtimes_agree`: same compiled query on the engine and through the real `Executor` over a DuckDB file.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/duckdb.py` (CREATE)
```python
"""DuckDB target for accounting queries (FEAT-713 M6)."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from parrot.interfaces.duckdb_engine import DuckDBEngine, FrameConversionError, to_arrow

from ..errors import AccountingExecutionError
from ..evaluation import evaluate_rows
from ..models import AccountingModel, CompiledMetricQuery, RuntimeResult

FrameProvider = Callable[[str], Awaitable[Any]]


class DuckDBRuntime:
    """Runs compiled accounting SQL over a provided frame on a shared DuckDBEngine."""

    def __init__(self, engine: DuckDBEngine, frame_provider: FrameProvider) -> None:
        self.engine = engine
        self.frame_provider = frame_provider
        self.logger = logging.getLogger(__name__)

    async def execute(self, compiled: CompiledMetricQuery, model: AccountingModel) -> RuntimeResult:
        """Fetch the model's frame, convert, run with a per-call registration, evaluate exactly.

        Raises:
            AccountingExecutionError: no dataframe source, dialect not 'duckdb', conversion or execution failure.
        """
        chart = model.spec.chart_of_accounts
        name = chart.source.dataframe
        if name is None or compiled.dialect != "duckdb":
            raise AccountingExecutionError("DuckDB runtime needs a dataframe source and a 'duckdb' compilation")
        started = time.monotonic()
        frame = await self.frame_provider(name)
        amount_columns = tuple(c for c in (chart.amount, chart.debit, chart.credit) if c)
        # FILL IN: validate exact frame values for amount_columns (DECIMAL(38,6) bounds) before conversion.
        try:
            table = to_arrow(frame, decimal_columns=amount_columns, allow_float=chart.allow_float)
            result = await self.engine.execute(compiled.sql, frames={name: table})
        except FrameConversionError as exc:
            raise AccountingExecutionError(str(exc)) from exc
        # FILL IN: wrap engine errors (duckdb exceptions) as AccountingExecutionError.
        rows = evaluate_rows(compiled.plan, result.to_pylist())
        # FILL IN: columns = bucket/dimension columns + plan output names, in plan order.
        return RuntimeResult(columns=tuple(rows[0]) if rows else (), rows=rows, target="duckdb",
                             duration_ms=int((time.monotonic() - started) * 1000))
```

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/database.py` (CREATE)
```python
"""Database target for accounting queries through the shipped semantic Executor (FEAT-713 M6)."""

from __future__ import annotations

import logging
import time
from typing import Sequence

from parrot.semantic.errors import SemanticExecutionError
from parrot.semantic.execution import Executor
from parrot.semantic.models import GovernedQuery

from ..errors import AccountingExecutionError
from ..evaluation import evaluate_rows
from ..models import AccountingModel, CompiledMetricQuery, RuntimeResult


class DatabaseRuntime:
    """Wraps compiled SQL in a GovernedQuery and runs it unchanged through Executor.run_with_columns."""

    def __init__(self, executor: Executor, *, result_limit: int = 10_000) -> None:   # Executor verified: execution.py:52
        self.executor = executor
        self.result_limit = result_limit
        self.logger = logging.getLogger(__name__)

    def dialect_for(self, model: AccountingModel) -> str:
        """executor.toolkit.get_source(driver).sqlglot_dialect (verified: toolkit.py:202, base.py:337)."""
        # FILL IN: driver required (table source); a source with sqlglot_dialect None ⇒ AccountingExecutionError.
        raise NotImplementedError

    async def execute(self, compiled: CompiledMetricQuery, model: AccountingModel, *,
                      subject_digest: str) -> RuntimeResult:
        """Executor.run_with_columns(governed, connection=...) (verified: execution.py:60). Truncated ⇒ error."""
        source = model.spec.chart_of_accounts.source
        governed = GovernedQuery(
            sql=compiled.sql, dialect=compiled.dialect, driver=source.driver, tables=(source.table,),
            rls_applied=(), masked_columns=(), limit=self.result_limit, subject_digest=subject_digest,
            members=((compiled.lineage.metric or f"assertion:{compiled.lineage.assertion_index}"),),
            physical_columns=(),  # FILL IN: declared journal columns (account_key, posting_date, amounts, dimensions)
        )
        started = time.monotonic()
        try:
            rows, _count, truncated, _ms, _columns = await self.executor.run_with_columns(
                governed, connection=source.connection)
        except SemanticExecutionError as exc:
            raise AccountingExecutionError(str(exc)) from exc
        if truncated:
            raise AccountingExecutionError(f"result exceeds {self.result_limit} groups; narrow the request")
        evaluated = evaluate_rows(compiled.plan, rows)
        return RuntimeResult(columns=tuple(evaluated[0]) if evaluated else (), rows=evaluated, target="database",
                             duration_ms=int((time.monotonic() - started) * 1000))

    async def fetch_chart_rows(self, *, connection: str, driver: str, table: str, columns: Sequence[str]) -> list[dict]:
        """SELECT DISTINCT of the account master through the executor; feeds snapshot_from_rows."""
        # FILL IN: build the SELECT with sqlglot exp (quoted identifiers, no string interpolation of user data),
        #   wrap in GovernedQuery with limit=self.result_limit, run, raise on truncation.
        raise NotImplementedError

    async def fetch_columns(self, *, connection: str, driver: str, table: str) -> dict[str, str]:
        """source.get_metadata(credentials, [table]) → {column name: data_type} (verified: base.py:429, :100)."""
        # FILL IN: credentials via self.executor.resolver.resolve(connection, driver); missing table ⇒ error.
        raise NotImplementedError
```

### `packages/ai-parrot-semantic/tests/accounting/test_runtime.py` (CREATE)
```python
"""FEAT-713 M6 — runtimes."""

from __future__ import annotations

import pytest


async def test_duckdb_runtime_uses_frame_provider(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    pytest.importorskip("duckdb")
    # FILL IN: provider records the requested name ("journal"); result amounts are Decimal; target "duckdb".


async def test_database_runtime_builds_governed_query(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: fake executor capturing GovernedQuery; sql == compiled.sql; all 10 fields set; connection passed.


async def test_database_runtime_truncation_raises(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: fake executor returns truncated=True ⇒ AccountingExecutionError; SemanticExecutionError re-raised.


async def test_runtimes_agree(troc_pnl_yaml, chart_snapshot, journal_frame, journal_duckdb_file) -> None:
    pytest.importorskip("duckdb")
    # FILL IN: engine rows == real Executor(DatabaseQueryToolkit(), ConnectionResolver(env)) rows over the DuckDB
    #   file (env PARROT_SEMANTIC_CONN_<NAME>_DATABASE=<file>); model variant with a table source.


async def test_exact_numeric_types(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: a frame with a value beyond DECIMAL(38,6) (or 7 fractional digits) ⇒ AccountingExecutionError
    #   before conversion.
```

### FILL IN checklist
- [ ] Frame value validation and engine error wrapping in `DuckDBRuntime.execute`.
- [ ] `dialect_for`, `physical_columns`, `fetch_chart_rows`, `fetch_columns` in `DatabaseRuntime`.
- [ ] Output column ordering; five tests.

---

## Acceptance Criteria

- [ ] The same compiled query gives equal `Decimal` rows on the engine and through the real `Executor` over a
  DuckDB file (AC10).
- [ ] Truncation raises; `SemanticExecutionError` is re-raised as `AccountingExecutionError`.
- [ ] Executed SQL text equals `compiled.sql`.
- [ ] `Executor`, `DatabaseQueryToolkit`, `DuckDBSource` are unchanged (AC10).
- [ ] `ruff check` passes on every touched file.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_runtime.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5533 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native opus coder (attempt 44be9eddc9fb483c8cfb7dc627bc2a24), commit 73b7977069
**Date**: 2026-11-12
**Notes**: `runtime/` package: DuckDBRuntime (DECIMAL(38,6) value checks and Arrow conversion off the event loop via asyncio.to_thread; engine errors reduced to the exception type name) and DatabaseRuntime (dialect_for, execute, fetch_chart_rows with quoted sqlglot identifiers, fetch_columns). 8 tests green incl. DuckDBEngine vs real Executor agreement.
Decisions for downstream tasks (TASK-5536/5537): (1) result columns are named `m_<metric>` as the compiler emits them (blueprint said bare metric name); (2) `fetch_chart_rows` uses module constant `CHART_SUBJECT_DIGEST = "accounting:chart-master"` for the GovernedQuery since the signature has no digest parameter; (3) database.py imports `output_columns` from runtime/duckdb.py (which never imports the duckdb package).

**Deviations from spec**: none
