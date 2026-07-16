---
type: Wiki Overview
title: 'TASK-1524: DependencyOperation model (copy/arithmetic/string-date/lookup-aggregate)'
id: doc:sdd-tasks-completed-task-1524-dependency-operation-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 2. Adds the `DependencyOperation` Pydantic model — the vocabulary
  for computing a
---

# TASK-1524: DependencyOperation model (copy/arithmetic/string-date/lookup-aggregate)

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1523
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Adds the `DependencyOperation` Pydantic model — the vocabulary for computing a
value from referenced field values (copy/assign, arithmetic, string/date, lookup/aggregation).
This is the data model only; actual evaluation lives in the `RuleEvaluator` (TASK-1530). The
model is then carried by `DependencyRule.operations` (here) and `PostDependency.operation`
(TASK-1525).

---

## Scope

- Add `DependencyOperation(BaseModel)` to `core/constraints.py` (or a new `core/operations.py`
  re-exported from `core/__init__.py` if the file grows large — prefer keeping it in
  `constraints.py` for cohesion with `DependencyRule`).
- Fields (per spec §2 Data Models): `op` (Literal of copy/add/subtract/multiply/divide/percent/
  concat/format/date_diff/lookup/aggregate), `operands: list[str]`, `target: str`,
  `options: dict[str, Any] | None = None`.
- Add an optional `operations: list[DependencyOperation] | None = None` field to `DependencyRule`.
- Add Pydantic validators: `operands` non-empty for ops that need them; `target` non-empty;
  unknown `op` rejected by the `Literal`.
- Export `DependencyOperation` from `core/__init__.py`.
- Unit tests for each op kind + invalid shapes.

**NOT in scope**: evaluating operations (TASK-1530); `PostDependency` (TASK-1525); reference
existence / type-compatibility validation against a form (TASK-1526) — here we only validate the
model's own shape.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` | MODIFY | Add `DependencyOperation`; add `operations` to `DependencyRule` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Export `DependencyOperation` |
| `packages/parrot-formdesigner/tests/` | CREATE/MODIFY | Tests for `DependencyOperation` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core import DependencyRule, DependencyOperation  # new export (this task)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class DependencyRule(BaseModel):                 # line 158 (logic widened in TASK-1523)
    conditions: list[FieldCondition]             # 167
    logic: Literal["and","or","xor","not"] = "and"   # 168 (after TASK-1523)
    effect: Literal["show","hide","require","disable"] = "show"  # 169
    # ADD: operations: list["DependencyOperation"] | None = None

# Pydantic imports already present at top of constraints.py:
# from pydantic import BaseModel, ConfigDict, Field, field_validator   (lines ~12)
# from typing import Any, Literal                                       (line 10)
```

### Does NOT Exist
- ~~`DependencyOperation`~~ — no operation/calc/derived-value model exists yet (this task creates it).
- ~~`DependencyRule.operations`~~ — not present today.
- ~~Any calculation/expression engine~~ — there is no evaluator; do not import one (TASK-1530 builds it).

---

## Implementation Notes

### Pattern to Follow
```python
class DependencyOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal[
        "copy", "add", "subtract", "multiply", "divide", "percent",
        "concat", "format", "date_diff", "lookup", "aggregate",
    ]
    operands: list[str]          # referenced field_ids (literal-operand encoding via options if needed)
    target: str
    options: dict[str, Any] | None = None

    @field_validator("operands")
    @classmethod
    def _non_empty_operands(cls, v): ...
```
Mirror the existing `FieldConstraints` validator style (constraints.py:58-126).

### Key Constraints
- Pydantic v2, `extra="forbid"` (consistent with `FieldConstraints`).
- Model-shape validation only; no form-context checks here.

### References in Codebase
- `core/constraints.py:17-126` — `FieldConstraints` validator patterns.
- `core/constraints.py:158-169` — `DependencyRule` to extend.

---

## Acceptance Criteria

- [ ] `DependencyOperation` constructs for every `op` kind with valid `operands`/`target`.
- [ ] Empty `operands` (for ops requiring them) and unknown `op` raise `ValidationError`.
- [ ] `DependencyRule(..., operations=[DependencyOperation(...)])` constructs; default `operations` is `None`.
- [ ] `from parrot_formdesigner.core import DependencyOperation` works.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k operation -v`
- [ ] `ruff check` clean on edited files.

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core import DependencyRule, DependencyOperation, FieldCondition, ConditionOperator

class TestDependencyOperation:
    @pytest.mark.parametrize("op", ["copy","add","subtract","multiply","divide","percent","concat","format","date_diff","lookup","aggregate"])
    def test_op_kinds(self, op):
        o = DependencyOperation(op=op, operands=["f1","f2"], target="f3")
        assert o.target == "f3"

    def test_unknown_op_rejected(self):
        with pytest.raises(ValidationError):
            DependencyOperation(op="frobnicate", operands=["f1"], target="f2")

    def test_rule_carries_operations(self):
        r = DependencyRule(
            conditions=[FieldCondition(field_id="f1", operator=ConditionOperator.EQ, value=1)],
            operations=[DependencyOperation(op="copy", operands=["f1"], target="f2")],
        )
        assert r.operations and r.operations[0].op == "copy"
```

---

## Agent Instructions

1. **Read the spec** §2 Data Models + §3 Module 2.
2. **Check dependencies** — TASK-1523 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before editing.
4. **Update index** → `"in-progress"`.
5. **Implement** model + `operations` field + export + tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: DependencyOperation model with all 11 op kinds (copy/add/subtract/multiply/divide/percent/concat/format/date_diff/lookup/aggregate). Validators for non-empty operands/target. Operations field added to DependencyRule. Exported from core/__init__.py. 51 tests pass.

**Deviations from spec**: Implemented together with TASK-1523/1525 in a single commit since they share constraints.py.
