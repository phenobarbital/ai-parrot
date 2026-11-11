# TASK-5540: End-to-end integration tests

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5537
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests, AC8/AC9/AC10/AC11. Proves the whole path — model → compile → DuckDB or executor →
exact evaluation → audit — on the 10k-row fixture journal against hand-computed `Decimal`s. Test-only task.

---

## Scope

- Create `tests/accounting/test_e2e_duckdb.py` with: `test_e2e_duckdb_pnl`, `test_e2e_duckdb_cumulative`,
  `test_weekly_cumulative_rejected`, `test_e2e_duckdb_file_through_executor`, `test_e2e_postgres_parity`
  (skipped unless `PARROT_TEST_PG_DSN`), `test_e2e_audit_trail`.
- Expected values are computed in the test from `journal_frame` with plain Python `Decimal` sums (never floats),
  not copied from engine output.

**NOT in scope**: any production code change. If a test exposes a defect, record it in the Completion Note and
open a ledger issue; do not fix production code here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/tests/accounting/test_e2e_duckdb.py` | CREATE | integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.accounting.toolkit import AccountingToolkit          # TASK-5536/5537
from parrot.semantic.accounting.audit import rebuild_lineage              # TASK-5534
from parrot.semantic.accounting.errors import RequestValidationError     # TASK-5524
from parrot.semantic.accounting.models import ChartSnapshot              # TASK-5525
import pyarrow as pa
```

### Existing Signatures to Use
```python
# AccountingToolkit(*, models_dir, snapshot_provider | snapshot_manifests, frame_provider, audit_storage, audit_mode, ...)
# await toolkit.query_metric(metric, period_from, period_to, model=None, grain=None, dimensions=None,
#                            filters=None, cumulative=None, tenant=None) -> dict
# Fixtures (tests/accounting/conftest.py): chart_snapshot, troc_pnl_yaml, journal_frame, journal_duckdb_file,
#   recording_storage, permission_context
# Executor path: ConnectionResolver env PARROT_SEMANTIC_CONN_<NAME>_<KEY> (SL/execution.py:21-48); DuckDB credential
#   key "database" (CORE/tools/databasequery/sources/duckdb.py:72-75)
```

### Does NOT Exist
- ~~a Postgres server in CI~~ — the parity test skips when `PARROT_TEST_PG_DSN` is unset.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_e2e_duckdb.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write a `toolkit` helper building an `AccountingToolkit` over the fixtures (dataframe source) and a variant
   with a DuckDB-file table source.
2. Write each test, computing expectations from `journal_frame` in Python.

### `packages/ai-parrot-semantic/tests/accounting/test_e2e_duckdb.py` (CREATE)
```python
"""FEAT-713 integration tests over the 10k-row fixture journal."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

pytest.importorskip("duckdb")


async def test_e2e_duckdb_pnl(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    # FILL IN: revenue, gross_margin, ebitda by month equal hand-computed Decimals; the assertion passes.


async def test_e2e_duckdb_cumulative(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    # FILL IN: mtd/qtd/ytd at supported grains equal cumulative sums; gross_margin_pct ytd == ytd gm / ytd revenue
    #   (rounded once); partial first and last buckets; month/quarter/year transitions — AC8.


async def test_weekly_cumulative_rejected(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    # FILL IN: week + ytd/qtd/mtd ⇒ RequestValidationError and the frame_provider is never called;
    #   non-cumulative weekly grouping is correct across Dec 31/Jan 1.


async def test_e2e_duckdb_file_through_executor(troc_pnl_yaml, chart_snapshot, journal_frame, journal_duckdb_file,
                                                tmp_path, monkeypatch) -> None:
    # FILL IN: table-source model variant over the DuckDB file via PARROT_SEMANTIC_CONN_* env; rows equal the
    #   engine rows — AC10.


@pytest.mark.skipif(not os.environ.get("PARROT_TEST_PG_DSN"), reason="PARROT_TEST_PG_DSN not set")
async def test_e2e_postgres_parity(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    # FILL IN: load the journal into a temp Postgres table; rows equal DuckDB rows; drop the table after.


async def test_e2e_audit_trail(troc_pnl_yaml, chart_snapshot, journal_frame, recording_storage) -> None:
    # FILL IN: N queries ⇒ N signed payloads; each lineage_ref rebuilds the same Lineage — AC11.
```

### FILL IN checklist
- [ ] Six test bodies with independently computed expectations.

---

## Acceptance Criteria

- [ ] All six tests pass (parity skips without a DSN) (AC8, AC9, AC10, AC11).
- [ ] No production file is modified.
- [ ] `ruff check` passes.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_e2e_duckdb.py -q`

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
9. **Close the task** with `parrot sdd task close TASK-5540 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
