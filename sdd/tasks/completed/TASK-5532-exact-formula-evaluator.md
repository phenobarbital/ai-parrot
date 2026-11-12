# TASK-5532: Exact formula evaluator

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5526
**Assigned-to**: unassigned

---

## Context

Spec revision 0.3 "Numeric and period contracts" and AC9. SQL returns exact per-set aggregates only; both runtimes
then call one shared evaluator, `evaluate_rows(plan, rows)`, which applies the plan's formulas with exact rational
arithmetic and rounds each final output **once** to scale 6, half-even, independent of the ambient `Decimal`
context. This task needs only the plan contracts, so it runs in parallel with the compiler.

---

## Scope

- Create `evaluation.py` with `evaluate_rows` and private helpers.
- Input validation per aggregate value: accept `Decimal`, `int`, or a finite decimal string that fits
  DECIMAL(38,6); reject `float` (including NaN/inf), `bool`, malformed strings ⇒ `AccountingExecutionError`.
  `None` aggregate ⇒ 0 (spec: NULL set aggregates normalise to zero).
- Evaluate each `plan.columns` expression with `fractions.Fraction` built from exact `Decimal`s; division by zero
  ⇒ `None`, which propagates through the rest of the expression.
- Quantize each final output to scale 6, half-even, using integer `divmod` on the scaled fraction — never
  `Decimal.quantize` under a context, never finite-precision division; convert the scaled integer to `Decimal`
  exactly. Result outside DECIMAL(38,6) ⇒ `AccountingExecutionError`.
- Output rows keep the grain bucket and dimension columns and replace set columns with the output columns.
- Create `tests/accounting/test_evaluation.py`: `test_exact_formula_evaluation`, `test_rounding_and_overflow`,
  `test_invalid_aggregate_values`.

**NOT in scope**: assertion pass/fail comparison (TASK-5537 compares the two quantized sides with tolerance);
running SQL (TASK-5533).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/evaluation.py` | CREATE | shared exact evaluator |
| `packages/ai-parrot-semantic/tests/accounting/test_evaluation.py` | CREATE | evaluator tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from fractions import Fraction
from decimal import Decimal
from parrot.semantic.accounting.errors import AccountingExecutionError   # TASK-5524; AccountingExecutionError(message, *, audit_id=None)
from parrot.semantic.accounting.models import MetricPlan, PlanExpr       # TASK-5526
```

### Existing Signatures to Use
```python
# models.py (TASK-5526)
class PlanExpr: op: Literal["set","num","neg","add","sub","mul","div"]; alias: str | None; value: str | None; args: tuple[PlanExpr, ...]
class MetricPlan: columns: tuple[tuple[str, PlanExpr], ...]; sets: tuple[PlanSet, ...]; grain; dimensions;
                  result_scale: Literal[6]; rounding: Literal["half_even"]; arithmetic_version: Literal[1]
```

### Does NOT Exist
- ~~`Decimal(str(value))` for floats~~ — forbidden by the spec; floats are rejected, never repaired.
- ~~`decimal.getcontext()`~~ / `localcontext` — results must not depend on the ambient context.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/evaluation.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_evaluation.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- DECIMAL(38,6) bound: `abs(value) < 10**32` and at most six fractional digits for inputs; for outputs the scaled
  integer must satisfy `abs(n) < 10**38`.
- Half-even on a `Fraction` f at scale 6: `n = f * 10**6`; `q, r = divmod(n.numerator, n.denominator)` (floor);
  compare `2*r` with the denominator; ties go to the even `q`. Then `Decimal(q).scaleb(-6)` is exact.
- Standard library + accounting package only (compile-path isolation).

---

## Implementation Blueprint

### Steps (in order)
1. Write `_to_fraction(value)` with all rejections — *why*: AC9 forbids float aggregates.
2. Write `_eval(expr, sets)` returning `Fraction | None`.
3. Write `_quantize(f)` and `evaluate_rows`.
4. Tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/evaluation.py` (CREATE)
```python
"""Shared exact formula evaluation (FEAT-713, spec numeric contract rev 0.3). Standard library only."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Mapping, Sequence

from .errors import AccountingExecutionError
from .models import MetricPlan, PlanExpr

_SCALE = 10**6
_MAX_INPUT_INTEGER = 10**32
_MAX_SCALED = 10**38


def _to_fraction(value: Any, *, column: str) -> Fraction:
    """Exact Fraction for one aggregate value; None ⇒ 0.

    Raises:
        AccountingExecutionError: float/bool/NaN/inf/malformed string, or a value outside DECIMAL(38,6).
    """
    # FILL IN: bool before int; Decimal must be finite with exponent >= -6; int; str parsed with Decimal then the
    #   same checks; anything else (float included) ⇒ AccountingExecutionError naming the column.
    raise NotImplementedError


def _eval(expr: PlanExpr, sets: Mapping[str, Fraction]) -> Fraction | None:
    """Exact evaluation; division by zero yields None, which propagates."""
    # FILL IN: set ⇒ sets[alias]; num ⇒ Fraction(Decimal(value)); neg/add/sub/mul/div.
    raise NotImplementedError


def _quantize(value: Fraction) -> Decimal:
    """Round once to scale 6, half-even, with integer arithmetic only; overflow ⇒ AccountingExecutionError."""
    # FILL IN: see Key Constraints.
    raise NotImplementedError


def evaluate_rows(plan: MetricPlan, rows: Sequence[Mapping[str, Any]]) -> tuple[dict, ...]:
    """Validate exact aggregates, evaluate formulas and round final columns once; preserve grain/dimensions.

    Raises:
        AccountingExecutionError: floats, malformed aggregates or precision/scale overflow.
    """
    aliases = [s.alias for s in plan.sets]
    out: list[dict] = []
    for row in rows:
        sets = {alias: _to_fraction(row.get(alias), column=alias) for alias in aliases}
        result = {key: value for key, value in row.items() if key not in sets}
        for name, expr in plan.columns:
            value = _eval(expr, sets)
            result[name] = None if value is None else _quantize(value)
        out.append(result)
    return tuple(out)
```

### `packages/ai-parrot-semantic/tests/accounting/test_evaluation.py` (CREATE)
```python
"""FEAT-713 — exact evaluation, rounding and rejection."""

from __future__ import annotations

from decimal import Decimal

import pytest

from parrot.semantic.accounting.errors import AccountingExecutionError
from parrot.semantic.accounting.evaluation import evaluate_rows


def test_exact_formula_evaluation() -> None:
    # FILL IN: hand-built MetricPlan; 9007199254740993 / 1 stays exact; 1/3 ⇒ Decimal("0.333333");
    #   nested cancellation ((a+b)-b)*c exact before the final rounding.


def test_rounding_and_overflow() -> None:
    # FILL IN: ±0.0000005 ties go half-even; signed division; values at the 38-digit limit pass, one beyond fails;
    #   intermediates beyond the default 28-digit Decimal context are exact.


@pytest.mark.parametrize("bad", [1.5, float("nan"), float("inf"), "1e3x", True, Decimal("NaN"), Decimal("0.0000001")])
def test_invalid_aggregate_values(bad) -> None:
    # FILL IN: AccountingExecutionError; also a zero denominator ⇒ None output (not an error).
    ...
```

### FILL IN checklist
- [ ] `_to_fraction`, `_eval`, `_quantize` — AC9.
- [ ] Three tests.

---

## Acceptance Criteria

- [ ] Exact intermediates; one final half-even rounding at scale 6; independent of `Decimal` context (AC9).
- [ ] Floats, NaN, infinity, bools and malformed strings are rejected; overflow raises (AC9).
- [ ] Division by zero yields `None` and propagates.
- [ ] `ruff check` passes on both files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_evaluation.py -q`

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
9. **Close the task** with `parrot sdd task close TASK-5532 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native sonnet coder (attempt c8336d859d9c4bd79c1fdc9fabbeb187), commit 55f5188a28
**Date**: 2026-11-12
**Notes**: `evaluate_rows` with exact Fraction arithmetic, one half-even rounding to scale 6, DECIMAL(38,6) bounds. Tests build MetricPlan via `model_construct`. Tests green, ruff clean.

**Deviations from spec**: none
