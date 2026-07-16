---
type: Wiki Overview
title: 'TASK-1530: Optional RuleEvaluator service (server-side authoritative resolution)'
id: doc:sdd-tasks-completed-task-1530-rule-evaluator-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 7 + §2 New Public Interfaces. Provides the optional, authoritative
  server-side
relates_to:
- concept: mod:parrot.forms
  rel: mentions
---

# TASK-1530: Optional RuleEvaluator service (server-side authoritative resolution)

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1526
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 + §2 New Public Interfaces. Provides the optional, authoritative server-side
evaluator (resolved decision, spec §8: schema is declarative for clients; Python evaluator is
authoritative server-side). Given a `FormSchema` + current answers, it resolves visibility,
required state, computed values (from operations), and cascade-clears — processing pre-deps,
post-deps, and operations in topological order.

---

## Scope

- Create `services/rule_evaluator.py` with:
  - `RuleResolution(BaseModel)`: `visible: dict[str,bool]`, `required: dict[str,bool]`,
    `computed: dict[str,Any]`, `cleared: list[str]`.
  - `RuleEvaluator` with `async def resolve(self, form, answers, *, locale="en") -> RuleResolution`.
- Evaluate `depends_on` logic including `and`/`or`/`xor`/`not` (use the `NOT` default from spec §8:
  `not` negates the AND-combination of conditions — document this in the code).
- Apply `effect` (show/hide/require/disable) to `visible`/`required`.
- Compute `operations` (copy/arithmetic/string-date/lookup/aggregate) into `computed`; process
  `post_depends` forward effects (set/calc/reload_options/show/hide/require/cascade_clear).
- Topologically order evaluation using the dependency graph; safe no-op on missing/empty referenced
  values and on lookup/op failure (record, never crash).
- Export `RuleEvaluator`/`RuleResolution` from `services/__init__.py`.
- Unit tests covering logic operators, each operation kind, cascade-clear, and safe-on-missing.

**NOT in scope**: toolkit/authoring (TASK-1528); renderer (TASK-1527); extractor round-trip /
legacy `parrot.forms` re-export (TASK-1531) — but DO add the `services/__init__.py` export here.
`reload_options` timing and ARRAY-operand aggregation scope are open questions (spec §8): implement
a conservative best-effort and leave a `# TODO(FEAT-234 open question)` marker.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py` | CREATE | `RuleEvaluator` + `RuleResolution` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | MODIFY | Export `RuleEvaluator`, `RuleResolution` |
| `packages/parrot-formdesigner/tests/` | CREATE | Evaluator tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services import RuleEvaluator, RuleResolution   # new (this task)
from parrot_formdesigner.core import (
    FormSchema, FormField, FormSection, FormSubsection, FieldType,
    DependencyRule, FieldCondition, ConditionOperator, PostDependency, DependencyOperation,
)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):
    sections: list[FormSection]
    def iter_all_fields(self) -> Iterator[FormField]    # yields all fields across sections
class FormSection(BaseModel):
    def iter_fields(self) -> Iterator[FormField]        # line 128 (flattens subsections)
class FormField(BaseModel):
    field_id: str                                       # 50
    depends_on: DependencyRule | None = None            # 61
    post_depends: list[PostDependency] | None = None    # TASK-1525

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class ConditionOperator(str, Enum)   # 129 (eq/neq/gt/lt/gte/lte/in/not_in/is_empty/is_not_empty)
class FieldCondition(BaseModel): field_id; operator; value   # 144
class DependencyRule(BaseModel): conditions; logic; effect; operations   # 158 (+xor/not, operations)
class DependencyOperation(BaseModel): op; operands; target; options      # TASK-1524
class PostDependency(BaseModel): target; effect; conditions; logic; operation  # TASK-1525

# Optional reuse for graph ordering:
# FormValidator._detect_circular_dependencies (validators.py:777) — reference for graph building
```

### Does NOT Exist
- ~~`RuleEvaluator` / `RuleResolution` / any visibility/compute engine~~ — none today (this task creates them).
- ~~`services/rule_evaluator.py`~~ — new file.
- ~~A condition-evaluation helper~~ — there is none reusable; the existing validator only checks shape/cycles, it does not evaluate condition truth against answers.

---

## Implementation Notes

### Pattern to Follow
Async service class (mirror `FormValidator` in `services/validators.py`). Build an evaluation order
from the dependency graph (reuse the edge-building approach from
`_detect_circular_dependencies`). Evaluate a `FieldCondition` against `answers[field_id]` per
`ConditionOperator`. For `logic`:
```python
results = [eval_condition(c, answers) for c in conditions]
match logic:
    case "and": ok = all(results)
    case "or":  ok = any(results)
    case "xor": ok = sum(bool(r) for r in results) == 1
    case "not": ok = not all(results)   # NOT negates the AND-group (spec §8 default)
```

### Key Constraints
- Async-first; `self.logger` for op failures.
- Missing/empty referenced value → operation no-op (do not crash); record nothing harmful.
- Deterministic ordering; detect-and-skip on any residual cycle (validator should have caught it).

### References in Codebase
- `services/validators.py:91-179, 777-827` — service + graph patterns.
- `core/constraints.py` — operator/operation/effect definitions.

---

## Acceptance Criteria

- [ ] `resolve()` returns correct `visible`/`required` for `and`/`or`/`xor`/`not` rules.
- [ ] `computed` reflects copy/arithmetic/string-date/aggregate operation results.
- [ ] `post_depends` forward effects apply (set/calc/show/hide/require); `cascade_clear` populates `cleared`.
- [ ] Missing/empty referenced values and lookup/op failures produce a safe no-op (no exception).
- [ ] `from parrot_formdesigner.services import RuleEvaluator, RuleResolution` works.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k "evaluator or resolve" -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.services import RuleEvaluator, RuleResolution
from parrot_formdesigner.core import (
    FormSchema, FormSection, FormField, FieldType,
    DependencyRule, FieldCondition, ConditionOperator, PostDependency, DependencyOperation,
)

@pytest.fixture
def evaluator():
    return RuleEvaluator()

class TestRuleEvaluator:
    async def test_xor_visibility(self, evaluator):
        ...  # xor of two conditions → visible iff exactly one true

    async def test_not_logic(self, evaluator):
        ...  # not negates the AND-group

    async def test_copy_operation_computes_value(self, evaluator):
        ...

    async def test_cascade_clear(self, evaluator):
        ...

    async def test_safe_on_missing_values(self, evaluator):
        ...  # no answer for referenced field → no crash, no spurious compute
```

---

## Agent Instructions

1. **Read the spec** §2 New Public Interfaces + §3 Module 7 + §8 (NOT semantics, reload_options/ARRAY open questions).
2. **Check dependencies** — TASK-1526 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm model fields (operations/post_depends) exist before coding.
4. **Update index** → `"in-progress"`.
5. **Implement** evaluator + resolution model + exports + tests; mark open-question TODOs.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Created `services/rule_evaluator.py` with `RuleResolution(BaseModel)` and `RuleEvaluator` class. `resolve(form, answers, *, locale)` evaluates pre-deps (depends_on) and post-deps in topological order. All 4 logic gates (and/or/xor/not) implemented. All 11 DependencyOperation kinds implemented: copy, add, subtract, multiply, divide, percent, concat, format, date_diff, lookup (safe no-op with TODO), aggregate (conservative sum/avg/min/max/count). Post-dependency effects: show/hide/require/disable/set/calc/reload_options (sentinel __reload__ with TODO)/cascade_clear. Topological sort uses DFS from depends_on edges. All operations are safe-on-missing (no exception on None/missing operands). Exported RuleEvaluator, RuleResolution from services/__init__.py. 31 tests pass.

**Deviations from spec**: None. TODOs left as specified: `reload_options` timing (open question §8) uses `__reload__` sentinel; `lookup` server-side table not yet specified; ARRAY aggregation scope uses flat operand list.
