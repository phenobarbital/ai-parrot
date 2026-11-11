# TASK-5531: Compiler, part 2 — SQL rendering, self-check, `compile_metric` and golden files

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5530
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (render half), §2 Overview step 4, "Numeric and period contracts", AC1/AC3/AC5/AC8/AC12/AC17.
`render_plan` turns a `MetricPlan` into deterministic SQL with sqlglot `exp.*` constructors. Revision 0.3: SQL
returns **exact per-set aggregates only** — never metric arithmetic or division; formulas stay in the plan and are
evaluated by TASK-5532. Golden `.sql` files (per dialect) and golden plan `.json` files are the review artifacts.

Design-bearing module (spec delegation table: "no").

---

## Scope

- Append to `compiler.py`: `render_plan`, `self_check`, `compile_metric`, `compile_assertion`, lineage building.
- SQL shape: inner scan selects grain bucket (`DATE_TRUNC(<grain>, posting_date)`), dimensions, and per set
  `COALESCE(SUM(CASE WHEN <account_key> IN (<sorted literals>) THEN <normalised amount> END), 0) AS set_<name>`,
  with amounts cast to the dialect's exact type (DuckDB `DECIMAL(38,6)`, Postgres `NUMERIC(38,6)`,
  BigQuery `BIGNUMERIC`); `WHERE posting_date >= scan_from AND posting_date < to_exclusive` plus filters;
  `GROUP BY` bucket + dimensions. Outer `SELECT` returns bucket, dimensions and set aliases `ORDER BY` bucket,
  dimensions. Cumulative: every set column becomes `SUM(set_x) OVER (PARTITION BY DATE_TRUNC(<window>, bucket),
  <dims> ORDER BY bucket)` and the outer filter is `bucket >= DATE_TRUNC(<grain>, output_from)`.
- Sign normalisation per `amount_convention` and nature (spec §2 table) via `CASE` on the account's nature from
  `plan.natures`.
- `self_check(sql, dialect, table=, columns=)`: re-parse; referenced tables ⊆ {table}; columns ⊆ declared ∪ aliases.
- `compile_metric` / `compile_assertion`: fill `sql_hash = sha256(dialect + "\n" + sql)`, `plan_hash`, `plan`,
  `request`, `lineage` (metric lineage: `metric=<name>`, `assertion_index=None`; assertion lineage: `metric=None`,
  index set; warning `division_by_zero_possible` when the formula has a `div`, `float_cast` when `cast_decimal`).
- Golden files under `tests/accounting/golden/{duckdb,postgres,bigquery}/*.sql` and `golden/plans/*.json` for at
  least: monthly revenue by entity, gross_margin_pct (ratio), ytd ebitda by month, the assertion.
- Append to `test_compiler.py`: `test_compile_deterministic`, `test_sign_normalisation_per_convention`,
  `test_cumulative_window_shape`, `test_self_check_rejects_foreign_columns`, `test_coalesce_and_no_sql_division`,
  `test_resolved_natures_compile_without_snapshot`.
- Create `test_golden.py` (`test_plan_golden`, `test_compile_golden_<dialect>` parametrised, plus a
  `REGENERATE_GOLDENS=1` env switch that rewrites files).
- Append `test_import_isolation` (compile a metric in the subprocess, no governed modules) to
  `test_import_isolation.py`.

**NOT in scope**: formula evaluation (TASK-5532); executing SQL (TASK-5533).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py` | MODIFY | rendering half |
| `packages/ai-parrot-semantic/tests/accounting/test_compiler.py` | MODIFY | rendering tests |
| `packages/ai-parrot-semantic/tests/accounting/test_golden.py` | CREATE | golden comparisons |
| `packages/ai-parrot-semantic/tests/accounting/golden/duckdb/*.sql` | CREATE | goldens |
| `packages/ai-parrot-semantic/tests/accounting/golden/postgres/*.sql` | CREATE | goldens |
| `packages/ai-parrot-semantic/tests/accounting/golden/bigquery/*.sql` | CREATE | goldens |
| `packages/ai-parrot-semantic/tests/accounting/golden/plans/*.json` | CREATE | plan goldens (FEAT-742 fixtures) |
| `packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py` | MODIFY | compile-path isolation test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import sqlglot                       # satellite pin sqlglot>=30.1,<31 (packages/ai-parrot-semantic/pyproject.toml); venv 30.23.0
from sqlglot import exp
# in-module (TASK-5530): plan_metric, plan_assertion, canonical_request
from parrot.semantic.accounting.errors import AccountingError                      # TASK-5524
from parrot.semantic.accounting.models import CompiledMetricQuery, Lineage, MetricPlan   # TASK-5526
```

### Existing Signatures to Use
```python
# test_import_isolation.py (TASK-5524) defines _run(code) and GOVERNED; append a test that uses them.
```
- Fixtures: `troc_pnl_yaml`, `chart_snapshot`.

### Does NOT Exist
- ~~`sqlglot.parse_one(f"...")` with model data~~ — forbidden; build with `exp.*` constructors only.
- ~~metric arithmetic in SQL~~ — revision 0.3 removed it; no `NULLIF`, no `/` between set columns.
- ~~golden SQL tests anywhere in the tree~~ — this task introduces the pattern.
- ~~`parrot.semantic.engines`~~ usage — no engine registration; `compiler.py` imports nothing from
  `parrot.semantic` outside `accounting`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_compiler.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_golden.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/golden/duckdb/*.sql", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/golden/postgres/*.sql", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/golden/bigquery/*.sql", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/golden/plans/*.json", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Render with `select.sql(dialect=dialect, pretty=False, identify=False)`.
- `render_plan` reads only the `MetricPlan` — anything the renderer needs must be a plan field.
- Dates are literals (`DATE 'YYYY-MM-DD'` via `exp.cast(exp.Literal.string(...), "DATE")`); no bind parameters,
  so the executed text equals the hashed text.
- Determinism: 50 compiles ⇒ one `sql_hash`; `IN` lists sorted; no timestamps.
- Golden files are written by running with `REGENERATE_GOLDENS=1` once, reviewed by eye, then committed.

---

## Implementation Blueprint

### Steps (in order)
1. Write `_amount_expr(plan)` (sign normalisation + exact cast) — *why*: every set column uses it.
2. Write `render_plan` (non-cumulative, then cumulative) and `self_check`.
3. Write `compile_metric` / `compile_assertion` with lineage.
4. Generate goldens, review them, write the tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py` (MODIFY — append)
```python
# AFTER — append at end of file, below `def plan_assertion(` (created by TASK-5530)
# occurrences: 1 (verify: grep -c '^def plan_assertion(' compiler.py)
# Add to the imports: `import hashlib`, `import sqlglot`, `from sqlglot import exp`,
#   `from .errors import AccountingError`, `from .models import CompiledMetricQuery, Lineage`.

_EXACT_TYPE = {"duckdb": "DECIMAL(38, 6)", "postgres": "NUMERIC(38, 6)", "bigquery": "BIGNUMERIC"}


def _amount_expr(plan: MetricPlan, dialect: str) -> exp.Expression:
    """Normalised, exactly-cast amount for one posting (spec §2 sign table)."""
    # FILL IN: per amount_convention build CASE on account nature using plan.natures; cast inputs to
    #   _EXACT_TYPE[dialect] before arithmetic; unknown dialect ⇒ AccountingError.
    raise NotImplementedError


def render_plan(plan: MetricPlan, dialect: str) -> str:
    """Render *plan* to SQL for *dialect*; deterministic; never returns SQL that fails the self-check."""
    # FILL IN: inner scan + outer select per Scope; cumulative windows; run self_check before returning.
    raise NotImplementedError


def self_check(sql: str, dialect: str, *, table: str, columns: frozenset[str]) -> None:
    """Re-parse and assert referenced tables/columns ⊆ declared; raise AccountingError otherwise."""
    # FILL IN: sqlglot.parse_one(sql, read=dialect); walk exp.Table / exp.Column; allow output aliases and the
    #   internal bucket alias.
    raise NotImplementedError


def _lineage(model: AccountingModel, plan: MetricPlan, *, metric: str | None, assertion_index: int | None,
             formula: str) -> Lineage:
    # FILL IN: sets used, assertion exprs touching the metric, warnings (division_by_zero_possible, float_cast).
    raise NotImplementedError


def _compiled(model: AccountingModel, request, plan: MetricPlan, dialect: str, lineage: Lineage) -> CompiledMetricQuery:
    sql = render_plan(plan, dialect)
    return CompiledMetricQuery(
        sql=sql, dialect=dialect, sql_hash=hashlib.sha256(f"{dialect}\n{sql}".encode()).hexdigest(),
        model_hash=model.model_hash, plan_hash=plan.plan_hash, plan=plan, request=request, lineage=lineage,
    )


def compile_metric(model: AccountingModel, request: MetricRequest, dialect: str) -> CompiledMetricQuery:
    """plan_metric + render_plan. Same (model_hash, canonical request, dialect) ⇒ byte-identical sql."""
    plan = plan_metric(model, request)
    lineage = _lineage(model, plan, metric=request.metric, assertion_index=None,
                       formula=model.spec.metrics[request.metric].expr)
    return _compiled(model, request, plan, dialect, lineage)


def compile_assertion(model: AccountingModel, request: AssertionRequest, dialect: str) -> CompiledMetricQuery:
    """plan_assertion + render_plan; lineage carries metric=None and the assertion index."""
    plan = plan_assertion(model, request)
    lineage = _lineage(model, plan, metric=None, assertion_index=request.assertion_index,
                       formula=model.spec.assertions[request.assertion_index].expr)
    return _compiled(model, request, plan, dialect, lineage)
```

### `packages/ai-parrot-semantic/tests/accounting/test_golden.py` (CREATE)
```python
"""FEAT-713 M5 — golden SQL and plans. REGENERATE_GOLDENS=1 rewrites the files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"
REGENERATE = os.environ.get("REGENERATE_GOLDENS") == "1"
CASES = {
    # FILL IN: name → MetricRequest / AssertionRequest kwargs for: revenue_by_entity_month,
    #   gross_margin_pct_month, ebitda_ytd_month, assertion_0.
}


def test_plan_golden(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: plan JSON (indent=2, sort_keys) equals golden/plans/<case>.json.


@pytest.mark.parametrize("dialect", ["duckdb", "postgres", "bigquery"])
def test_compile_golden(dialect: str, troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: compile each case; equals golden/<dialect>/<case>.sql byte-for-byte (AC5).
```

### `packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py` (MODIFY — append)
```python
def test_import_isolation(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    """Compiling a metric in a fresh interpreter loads no governed-stack module (AC1)."""
    # FILL IN: dump chart_snapshot JSON to tmp_path; in _run(...) load it, load_model(troc_pnl_yaml), compile_metric
    #   for "duckdb", then print the GOVERNED modules present; assert output "[]".
```

### FILL IN checklist
- [ ] `_amount_expr`, `render_plan`, `self_check`, `_lineage` — AC3/AC8/AC12.
- [ ] Golden cases + files; six `test_compiler.py` additions; `test_import_isolation`.

---

## Acceptance Criteria

- [ ] Generated SQL contains set aggregates only — no metric arithmetic or division (spec rev 0.3, AC9).
- [ ] 50 compiles ⇒ one `sql_hash`; goldens for duckdb, postgres, bigquery match byte-for-byte (AC5).
- [ ] Cumulative SQL widens the scan, partitions by natural window, filters output by bucket and keeps the
  partial first bucket (AC8).
- [ ] Every rendered SQL passes `self_check` (AC12); a tampered SQL fails it.
- [ ] A from_column model compiles from its JSON round-trip with no snapshot (AC3).
- [ ] Compiling in a fresh interpreter loads no governed module (AC1).
- [ ] `ruff check` passes on every touched Python file.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_compiler.py -q`
- `pytest packages/ai-parrot-semantic/tests/accounting/test_golden.py -q`
- `pytest packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py -q`

---

## Test Specification

See blueprint and Scope list.

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
9. **Close the task** with `parrot sdd task close TASK-5531 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
