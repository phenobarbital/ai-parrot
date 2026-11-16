# TASK-5530: Compiler, part 1 — request validation and `MetricPlan` construction

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5526, TASK-5529
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (plan half), §2 Overview step 3, "Numeric and period contracts", AC7/AC8/AC17. `plan_metric`
validates a `MetricRequest` against a loaded model and produces a `MetricPlan`: plain, JSON-serialisable data with
no sqlglot objects — the portable IR the Rust compiler (FEAT-742) will port. TASK-5531 renders plans to SQL.

Design-bearing module (spec delegation table: "no").

---

## Scope

- Create `compiler.py` with `canonical_request`, `plan_metric`, `plan_assertion` and private helpers.
- `plan_metric`: metric exists; dimensions ⊆ metric dimensions (or chart dimensions when `None`); filters only on
  declared dimensions; cumulative/grain already checked by the request model; the requested period — and for
  cumulative requests the widened scan window — lies inside one membership interval, else
  `PeriodSpansMembershipChange(boundary, suggestion)`; every referenced set is active in that interval, else
  `RequestValidationError`; inline metric refs (via `metric_order`); dedupe sets; lower the AST to `PlanExpr`;
  copy the needed subset of `model.natures`.
- Window bounds: `to_exclusive = period.to + 1 day`; `output_from = period.from_`; `scan_from` = start of the
  natural window (month/quarter/year) containing `period.from_` for mtd/qtd/ytd, else `period.from_`.
- `plan_assertion(model, AssertionRequest)`: index in range else `RequestValidationError`; both sides lowered into
  `columns` as `("lhs", …)` and `("rhs", …)`.
- `tests/accounting/test_compiler.py`: `test_plan_is_plain_json`, `test_refuse_membership_change`,
  `test_request_validation_errors`, `test_plan_assertion_index`, `test_plan_hash_formula_identity`.

**NOT in scope**: `render_plan`, `compile_metric`, `compile_assertion`, `self_check`, goldens (TASK-5531);
evaluating formulas (TASK-5532).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py` | CREATE | planning half |
| `packages/ai-parrot-semantic/tests/accounting/test_compiler.py` | CREATE | planning tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.accounting.errors import PeriodSpansMembershipChange, RequestValidationError   # TASK-5524
from parrot.semantic.accounting.grammar import BinOp, Expr, Neg, Num, Ref, Sum, parse_assertion, parse_expr  # TASK-5527
from parrot.semantic.accounting.models import (AccountingModel, AccountingRequest, AssertionRequest,         # TASK-5525/5526
    MetricPlan, MetricRequest, PlanExpr, PlanSet)
from parrot.semantic.accounting.validation import metric_order                                      # TASK-5528
```

### Existing Signatures to Use
```python
# models.py (TASK-5526)
class CompiledMetricQuery: cache_key  # json.dumps([model_hash, <request JSON>, dialect]) where
#   <request JSON> = json.dumps(request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
```
`canonical_request` MUST return exactly that `<request JSON>` string.

### Does NOT Exist
- ~~sqlglot~~ in this half — planning imports no sqlglot (the renderer does).
- ~~`parrot.semantic.*` imports outside `accounting`~~ — forbidden in `compiler.py` (spec §3 M5).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_compiler.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Set alias: `set_<name>`; metric column alias: `m_<metric>`; aliases come from model names only.
- `PlanExpr` lowering: `Sum` ⇒ `op="set", alias="set_<name>"`; `Num` ⇒ `op="num", value=str(decimal)`;
  `Neg` ⇒ `neg`; `BinOp` ⇒ `add|sub|mul|div`; `Ref` is inlined recursively.
- `PlanSet.accounts` sorted; `MetricPlan.sets` sorted by alias; `filters` sorted by column, values sorted.
- `table`: `source.table` or `source.dataframe`; `cast_decimal = chart.allow_float`.
- The `suggestion` of `PeriodSpansMembershipChange` names the two sub-periods to request instead.
- Deterministic: same model + request ⇒ equal plans (and `plan_hash`).

---

## Implementation Blueprint

### Steps (in order)
1. Write `canonical_request` and the window helpers.
2. Write AST → `PlanExpr` lowering with ref inlining.
3. Write `plan_metric` validations in the Scope order, then `plan_assertion`.
4. Tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py` (CREATE)
```python
"""Accounting compiler (FEAT-713 M5). Planning half; rendering is appended by TASK-5531.

Imports nothing from parrot.semantic outside the accounting package.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from pydantic import TypeAdapter

from .errors import PeriodSpansMembershipChange, RequestValidationError
from .grammar import BinOp, Expr, Neg, Num, Ref, Sum, parse_assertion, parse_expr
from .models import (
    AccountingModel, AccountingRequest, AssertionRequest, MetricPlan, MetricRequest, PlanExpr, PlanSet,
)
from .validation import metric_order

_REQUEST = TypeAdapter(AccountingRequest)


def canonical_request(request: MetricRequest | AssertionRequest) -> str:
    """Sorted-key compact JSON of the request, by alias — the cache-key and audit form."""
    return json.dumps(request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))


def _window_start(day: date, cumulative: str | None) -> date:
    """Start of the natural month / quarter / year containing *day*; *day* itself when not cumulative."""
    # FILL IN
    raise NotImplementedError


def _lower(expr: Expr, model: AccountingModel, seen: frozenset[str] = frozenset()) -> PlanExpr:
    """Lower an AST to PlanExpr, inlining metric references (cycles were rejected at load)."""
    # FILL IN: see Key Constraints.
    raise NotImplementedError


def _interval_for(model: AccountingModel, start: date, end_exclusive: date) -> tuple[date | None, date | None]:
    """The single membership interval containing [start, end_exclusive); else PeriodSpansMembershipChange."""
    # FILL IN: first interval boundary strictly inside the window is the reported boundary.
    raise NotImplementedError


def plan_metric(model: AccountingModel, request: MetricRequest) -> MetricPlan:
    """Dialect-independent, JSON-serialisable plan. Raises RequestValidationError / PeriodSpansMembershipChange."""
    # FILL IN: Scope validations in order, then build MetricPlan.
    raise NotImplementedError


def plan_assertion(model: AccountingModel, request: AssertionRequest) -> MetricPlan:
    """Plan both sides of model.spec.assertions[request.assertion_index] over request.period (no grain)."""
    # FILL IN
    raise NotImplementedError
```

### `packages/ai-parrot-semantic/tests/accounting/test_compiler.py` (CREATE)
```python
"""FEAT-713 M5 — planning."""

from __future__ import annotations


def test_plan_is_plain_json(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: MetricPlan JSON round-trip; no sqlglot object anywhere (walk model_dump); plan_hash stable.


def test_refuse_membership_change(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: a period crossing 2025-01-01 (d&a valid_from), and a ytd window crossing it, raise
    #   PeriodSpansMembershipChange whose boundary == date(2025, 1, 1) — AC7.


def test_request_validation_errors(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: unknown metric, unknown dimension, filter on undeclared column ⇒ RequestValidationError.


def test_plan_assertion_index(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: index 0 plans lhs/rhs; out-of-range ⇒ RequestValidationError.


def test_plan_hash_formula_identity(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: two metrics over the same sets ⇒ same sets in plan, different plan_hash.
```

### FILL IN checklist
- [ ] `_window_start`, `_lower`, `_interval_for`, `plan_metric`, `plan_assertion` — AC7/AC8/AC17.
- [ ] Five tests.

---

## Acceptance Criteria

- [ ] Requests crossing a membership boundary (incl. widened cumulative windows) raise
  `PeriodSpansMembershipChange` naming the boundary and a split suggestion (AC7).
- [ ] Plans contain no sqlglot object and round-trip through JSON (AC17).
- [ ] Same-set formulas produce different `plan_hash` (spec numeric contract).
- [ ] `compiler.py` imports nothing from `parrot.semantic` outside `accounting`.
- [ ] `ruff check` passes on both files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_compiler.py -q`

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
9. **Close the task** with `parrot sdd task close TASK-5530 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native opus coder (attempt 088ec4fc279249009f3ecf550fcf09cd), commit 77ceeb4038
**Date**: 2026-11-12
**Notes**: compiler.py (canonical_request, plan_metric, plan_assertion) + 5 tests green. Open-spec decisions: filters allowed on any chart_of_accounts dimension, grouping limited to the metric's dimensions; duplicate dimensions / empty filter lists raise RequestValidationError; filter values de-duplicated and sorted (ints before strings); metric_order used only for the metric-exists check, references inlined recursively. The blueprint's `_REQUEST = TypeAdapter(AccountingRequest)` is kept but unused; `Decimal` import dropped.

**Deviations from spec**: none
