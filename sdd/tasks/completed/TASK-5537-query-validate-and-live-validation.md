# TASK-5537: `query_metric`, `validate_model` and live validation

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5536
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (query/validate) and Module 9 (`live.py`), AC9/AC11/AC13/AC15. Adds the two remaining tools to
`AccountingToolkit` and the live-validation module. `query_metric` compiles (cached), runs on the model's runtime,
evaluates exactly, audits, and returns rows + lineage. `validate_model` requires the model-validation privilege and
read access to every metric of the model before any refresh or disclosure. `run_live_validation(toolkit)` is the
trusted host-only entry point the scheduler (TASK-5538) calls; the public tool calls a private one-model helper.

---

## Scope

- `toolkit.py` (append): `query_metric`, `validate_model`, private `_compile`, `_runtime_for`, `_run_assertions`.
  - `query_metric` flow (spec §3 M8): resolve spec → authorize the metric → `_ensure_loaded` → block check
    (catalog flags `blocked` ⇒ `AccountingExecutionError`) → compile through `CompileCache` (key
    `CompiledMetricQuery.cache_key`; compile in `asyncio.to_thread`) → runtime → audit (`append_entry`, mode from
    the toolkit) → return `{columns, rows, row_count, lineage, sql_hash, plan_hash, audit_id, chart_drift,
    duration_ms}`; rows serialise Decimals as strings.
  - `validate_model`: when guard + context exist, require `accounting:<tenant>:<model>:__validate__` **and** every
    metric of the model; deny the whole request before snapshot refresh, compilation, execution or disclosure.
    Structural: return load problems (or none). `live=True`: call `live._validate_one(...)` for this model only.
- `live.py`: `ModelLiveStatus`, `LiveValidationReport`, `last_closed_month`, `_validate_one(toolkit, tenant,
  model, *, today)` (fresh snapshot via the provider, `detect_drift`, one `AssertionRequest` per assertion index
  for the last closed natural month, compile + run + audit each, compare quantized sides with `tolerance`; a NULL
  side ⇒ `skipped`; set flags), and `run_live_validation(toolkit, *, today=None)` iterating every configured spec.
  A failed refresh never clears previous flags and reports failure for that model.
- Append to `test_toolkit.py`: `test_toolkit_tools_and_prefix`, `test_query_metric_duckdb`, `test_query_metric_audits`,
  `test_validate_model_authorization`, `test_snapshot_refresh_failure`.
- `tests/accounting/test_live.py`: `test_last_closed_month`, `test_live_validation_flags`,
  `test_assertion_entries_replayable`.

**NOT in scope**: scheduler adapter (TASK-5538); CLI (TASK-5539); large e2e journals (TASK-5540).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/toolkit.py` | MODIFY | `query_metric`, `validate_model` |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/live.py` | CREATE | live validation |
| `packages/ai-parrot-semantic/tests/accounting/test_toolkit.py` | MODIFY | query/validate tests |
| `packages/ai-parrot-semantic/tests/accounting/test_live.py` | CREATE | live tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.accounting.compiler import compile_assertion, compile_metric        # TASK-5531
from parrot.semantic.accounting.audit import append_entry, build_entry, subject_digest   # TASK-5534
from parrot.semantic.accounting.loader import detect_drift                               # TASK-5529
from parrot.semantic.accounting.models import (AssertionRequest, AssertionResult, MetricRequest, Period)  # TASK-5526
from parrot.semantic.accounting.runtime.duckdb import DuckDBRuntime                      # TASK-5533
from parrot.interfaces.duckdb_engine import DuckDBEngine                                 # TASK-5523
from parrot.auth.context import _pctx_var                                                # CORE/auth/context.py:33
from parrot.auth.exceptions import AuthorizationRequired                                 # CORE/auth/exceptions.py:15
```

### Existing Signatures to Use
```python
# toolkit.py (TASK-5536): self._catalog, self._snapshot_provider, self._frame_provider, self._engine,
#   self._duckdb_threads, self._policy_guard, self._ledger, self._audit_mode, self._cache, self._database,
#   self._resolve_tenant(t), self._resource(t, m, metric), self._authorize(tool, names), self._ensure_loaded(t, m)
# catalog.py (TASK-5535): specs(), get(t, m), flags(t, m), set_flags(status), reload(snapshots, columns)
# SL/cache.py: CompileCache.get(key) / put(compiled) / invalidate_model(model_digest)
# runtime: DuckDBRuntime(engine, frame_provider).execute(compiled, model);
#          DatabaseRuntime.execute(compiled, model, *, subject_digest); DatabaseRuntime.dialect_for(model)
# audit.py: build_entry(*, context, tenant, model, compiled, target, tool, outcome, assertion_status, row_count,
#           duration_ms); append_entry(ledger, entry, *, mode)
```

### Does NOT Exist
- ~~a caller-controlled flag enabling trusted scheduler access~~ — forbidden (spec §3 M9).
- ~~result caching~~ — compile cache only (non-goal).
- ~~`run_live_validation` exposed as a tool~~ — it lives in `live.py`, not on the toolkit.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/live.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_live.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Only `list_metrics`, `explain_metric`, `query_metric`, `validate_model` are public coroutines (AC13).
- Audit before returning: under `required` an `AccountingAuditError` propagates and no rows are returned (AC11).
- An execution failure is audited with `outcome="execution_error"` (best effort) before re-raising.
- `live.py` imports `toolkit` only under `TYPE_CHECKING` (it receives the instance).
- Fresh snapshots detect drift without silently changing the loaded model/hash.
- `last_closed_month(today)` = the full natural month before `today`'s month.

---

## Implementation Blueprint

### Steps (in order)
1. `live.py` models + `last_closed_month`.
2. `toolkit.query_metric` with `_compile` / `_runtime_for`.
3. `live._validate_one` and `run_live_validation`, then `toolkit.validate_model`.
4. Tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/toolkit.py` (MODIFY — append inside the class)
```python
# AFTER — inside class AccountingToolkit, below `async def explain_metric(` (TASK-5536)
# occurrences: 1 (verify: grep -c 'async def explain_metric(' toolkit.py)

    async def query_metric(self, metric: str, period_from: str, period_to: str, model: str | None = None,
                           grain: str | None = None, dimensions: list[str] | None = None,
                           filters: dict | None = None, cumulative: str | None = None,
                           tenant: str | None = None) -> dict:
        """Compile → execute (database or duckdb) → audit → rows + lineage + sql_hash + audit_id + chart_drift."""
        # FILL IN: flow in Scope; RequestValidationError for bad inputs before any snapshot access.
        raise NotImplementedError

    async def validate_model(self, model: str, tenant: str | None = None, live: bool = False) -> dict:
        """Require validation privilege and all metric reads; return only the selected model's results.
        With live=True refresh its snapshot and run last-closed-month assertions plus drift."""
        # FILL IN: authorize __validate__ + every metric first; structural ⇒ {"model", "problems": [...]};
        #   live ⇒ from .live import _validate_one; return its ModelLiveStatus as a dict.
        raise NotImplementedError

    def _runtime_for(self, model) -> tuple[Any, str]:
        """(runtime, dialect): DuckDBRuntime for dataframe sources (engine created lazily), else DatabaseRuntime."""
        # FILL IN
        raise NotImplementedError

    async def _compile(self, model, request, dialect: str):
        """Cached compile in a worker thread; metric or assertion by request kind."""
        # FILL IN
        raise NotImplementedError
```

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/live.py` (CREATE)
```python
"""Live validation of accounting models: drift + assertions (FEAT-713 M9). Trusted host entry point."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .models import AssertionResult, Period

if TYPE_CHECKING:
    from .toolkit import AccountingToolkit


class ModelLiveStatus(BaseModel, frozen=True):
    tenant: str
    model: str
    drift_accounts: tuple[str, ...]
    assertion_results: tuple[AssertionResult, ...]
    audit_ids: tuple[str, ...]
    blocked: bool
    checked_at: datetime
    error: str | None = None


class LiveValidationReport(BaseModel, frozen=True):
    models: tuple[ModelLiveStatus, ...]


def last_closed_month(today: date) -> Period:
    """The full natural month before *today*'s month."""
    first = today.replace(day=1)
    end = first - timedelta(days=1)
    return Period(from_=end.replace(day=1), to=end)


async def _validate_one(toolkit: "AccountingToolkit", tenant: str, model: str, *, today: date) -> ModelLiveStatus:
    """Refresh one model's snapshot, detect drift, run and audit every assertion; set catalog flags."""
    # FILL IN: provider failure ⇒ status with error set, previous flags preserved (do not call set_flags);
    #   blocked = any failed assertion with on_failure == "block".
    raise NotImplementedError


async def run_live_validation(toolkit: "AccountingToolkit", *, today: date | None = None) -> LiveValidationReport:
    """Validate every configured model; never a tool."""
    today = today or datetime.now(timezone.utc).date()
    statuses = [await _validate_one(toolkit, t, m, today=today) for (t, m) in sorted(toolkit._catalog.specs())]
    return LiveValidationReport(models=tuple(statuses))
```

### `packages/ai-parrot-semantic/tests/accounting/test_toolkit.py` (MODIFY — append)
```python
async def test_toolkit_tools_and_prefix(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: sorted tool names == ["finance_explain_metric", "finance_list_metrics", "finance_query_metric",
    #   "finance_validate_model"].


async def test_query_metric_duckdb(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    # FILL IN: frame_provider returns journal_frame; rows have Decimal-string amounts; sql_hash/plan_hash present.


async def test_query_metric_audits(troc_pnl_yaml, chart_snapshot, journal_frame, recording_storage) -> None:
    # FILL IN: one payload per query; required mode + failing sink ⇒ AccountingAuditError and no result.


async def test_validate_model_authorization(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    # FILL IN: missing __validate__ or any metric read ⇒ AuthorizationRequired and the provider is never called;
    #   fully authorized ⇒ result for that model only.


async def test_snapshot_refresh_failure(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    # FILL IN: provider fails on refresh ⇒ previous flags/model/hash preserved and failure reported.
```

### `packages/ai-parrot-semantic/tests/accounting/test_live.py` (CREATE)
```python
"""FEAT-713 M9 — live validation."""

from __future__ import annotations

from datetime import date


def test_last_closed_month() -> None:
    # FILL IN: date(2026, 3, 15) ⇒ 2026-02-01..2026-02-28; January ⇒ previous December.


async def test_live_validation_flags(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    # FILL IN: a failing flag assertion ⇒ assertion_failed on later query results; on_failure block ⇒ query raises.


async def test_assertion_entries_replayable(troc_pnl_yaml, chart_snapshot, journal_frame, recording_storage) -> None:
    # FILL IN: every assertion entry's request_canonical is an AssertionRequest; rebuild_lineage succeeds.
```

### FILL IN checklist
- [ ] `query_metric`, `validate_model`, `_runtime_for`, `_compile`.
- [ ] `_validate_one`.
- [ ] Eight tests.

---

## Acceptance Criteria

- [ ] Exactly four `finance_*` tools (AC13).
- [ ] Every executed query appends one signed entry; required mode fails closed (AC11).
- [ ] `validate_model` denies before refresh/compile/execute/disclosure without the validation privilege or any
  metric read (AC13).
- [ ] Live validation sets flags; `block` makes `query_metric` raise; refresh failure preserves flags (AC15).
- [ ] `ruff check` passes on every touched file.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_toolkit.py -q`
- `pytest packages/ai-parrot-semantic/tests/accounting/test_live.py -q`

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
9. **Close the task** with `parrot sdd task close TASK-5537 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native opus coder (attempt 4fb61e08638246958878041f4326664e), commit be519d3459
**Date**: 2026-11-12
**Notes**: `query_metric`, `validate_model` (structural + live) on the toolkit; new `accounting/live.py` (ModelLiveStatus, LiveValidationReport, last_closed_month, _validate_one, run_live_validation). Compilation is cached and runs via asyncio.to_thread (thread-id spy test + cache-hit check); audit entry appended before returning (required mode propagates AccountingAuditError); PBAC checked before any snapshot/load/compile/execute/audit; failures keep previous catalog flags. 15 tests green, ruff clean.

**Deviations from spec**: `query_metric` also returns `assertion_failed` (needed by spec M9 / AC15); extra private helpers `_execute`, `_metric_request`, `_run_assertions` (a toolkit method called by live._validate_one). Reviewer note: the full pytest run printed a "Logging error: I/O operation on closed file" traceback from parrot/observability shutdown_telemetry after all tests passed; not investigated.
