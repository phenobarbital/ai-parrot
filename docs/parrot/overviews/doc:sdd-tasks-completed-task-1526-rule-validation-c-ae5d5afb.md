---
type: Wiki Overview
title: 'TASK-1526: FormValidator rule-integrity pass + extended cycle detection'
id: doc:sdd-tasks-completed-task-1526-rule-validation-cycle-detection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 4 — the heart of the authoring infrastructure. Adds a rule-integrity
  validation
---

# TASK-1526: FormValidator rule-integrity pass + extended cycle detection

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1523, TASK-1524, TASK-1525
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the heart of the authoring infrastructure. Adds a rule-integrity validation
pass to `FormValidator` and extends the circular-dependency detector to include `post_depends` and
operation edges. This is what makes dependencies *authorable*: invalid rules are rejected at
build/edit time instead of failing silently at render.

---

## Scope

- Add a rule-integrity pass (new method, e.g. `validate_rules(form) -> list[str]`, called from
  `validate`) that checks:
  - Every `field_id` in `depends_on.conditions`, `post_depends.conditions`, operation `operands`,
    and `post_depends.target` / operation `target` resolves to a real field in the form.
  - **Ordering**: a `depends_on` condition may only reference fields declared *earlier*; a
    `post_depends.target` (and `set`/`calc` operation `target`) may only reference fields declared
    *later* than the owning field.
  - **Operator/type compatibility**: numeric operators (`gt/lt/gte/lte`) and arithmetic ops only on
    numeric field types; arithmetic op operands must be numeric; etc. (best-effort, by `FieldType`).
- Extend `_detect_circular_dependencies` (validators.py:777) so the dependency graph adds edges from
  `post_depends` (owner → target) and operations (target → operands), reusing the existing DFS.
- Wire the new checks into `FormValidator.validate` (validators.py:112), surfacing errors in the
  returned `ValidationResult`.
- Unit tests for each failure mode + a clean-form passing case.

**NOT in scope**: evaluating rules/computing values (TASK-1530); toolkit/authoring UX (TASK-1528);
renderer changes (TASK-1527).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | Rule-integrity pass + extended cycle detection + wiring |
| `packages/parrot-formdesigner/tests/` | CREATE/MODIFY | Tests for ordering, references, types, cycles |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services import FormValidator, ValidationResult
from parrot_formdesigner.core import (
    FormSchema, FormField, FormSection, FormSubsection, FieldType,
    DependencyRule, PostDependency, DependencyOperation, FieldCondition, ConditionOperator,
)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:                                                  # line 91
    async def validate(self, form, data, *, locale="en") -> ValidationResult   # 112
        #   currently calls self._detect_circular_dependencies(form) at line 135
    async def validate_field(self, field, value, *, all_data=None, locale) -> list[str]  # 179
    def _detect_circular_dependencies(self, form: FormSchema) -> list[str]      # 777
        #   builds graph: field_id -> {referenced field_ids from depends_on.conditions}; DFS cycle detect
        #   uses helper self._collect_fields(section) to gather fields (referenced at line ~792)

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSection(BaseModel):                       # line 102
    fields: list[SectionItem]                       # 124  (SectionItem = FormField | FormSubsection, line 99)
    def iter_fields(self) -> Iterator[FormField]    # 128  (flattens subsections — USE THIS for ordered field list)
class FormSchema(BaseModel):                        # (sections: list[FormSection]); has iter_all_fields()
class FormField(BaseModel):
    depends_on: DependencyRule | None               # 61
    post_depends: list[PostDependency] | None       # added in TASK-1525
```

### Does NOT Exist
- ~~A rule **evaluator** / visibility engine in validators.py~~ — only cycle detection + field validation exist.
- ~~Ordering/type-compatibility checks for dependencies~~ — none today (this task adds them).
- ~~`_detect_circular_dependencies` awareness of `post_depends`/operations~~ — it currently walks only `depends_on.conditions` (line ~798).

---

## Implementation Notes

### Pattern to Follow
Reuse the existing DFS in `_detect_circular_dependencies` (validators.py:777-827). Add edges:
```python
# existing: depends_on edge  field -> condition.field_id
# add:       post_depends    field -> post.target  (and operation target -> operands)
```
Build a stable ordered list of `field_id`s using `FormSchema.iter_all_fields()` / `section.iter_fields()`
so "earlier/later" ordering is well-defined for the ordering check.

### Key Constraints
- Async-first (`validate` is async); the new helper methods may be sync where they don't do I/O.
- Aggregate errors into `ValidationResult` rather than raising mid-pass.
- Best-effort type checks must not crash on unknown/extension field types — degrade gracefully.

### References in Codebase
- `services/validators.py:777-827` — DFS cycle detector to extend.
- `core/schema.py:128` (`iter_fields`) + `iter_all_fields` — ordered traversal.

---

## Acceptance Criteria

- [ ] Unknown `field_id` in a condition/operand/target → error in `ValidationResult`.
- [ ] `depends_on` referencing a later field → error; `post_depends.target` referencing an earlier field → error.
- [ ] Numeric operator/arithmetic op on a non-numeric field → error.
- [ ] A cycle introduced via `post_depends`/operation is detected.
- [ ] A clean form with valid pre/post rules validates with no rule errors.
- [ ] Existing `depends_on`-only forms validate exactly as before (no regression).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k "validator or cycle or rule" -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.services import FormValidator
from parrot_formdesigner.core import (
    FormSchema, FormSection, FormField, FieldType,
    DependencyRule, FieldCondition, ConditionOperator, PostDependency, DependencyOperation,
)

@pytest.fixture
def validator():
    return FormValidator()

class TestRuleIntegrity:
    async def test_unknown_reference_errors(self, validator):
        ...  # condition referencing a non-existent field_id → error

    async def test_pre_dependency_must_reference_earlier(self, validator):
        ...  # depends_on referencing a later field → error

    async def test_post_dependency_must_target_later(self, validator):
        ...  # post_depends.target referencing an earlier field → error

    def test_cycle_via_post_depends_detected(self, validator):
        ...  # f1.post_depends -> f2 and f2.post_depends -> f1 → cycle reported

    async def test_clean_form_passes(self, validator):
        ...  # valid pre + post rules → no rule errors
```

---

## Agent Instructions

1. **Read the spec** §2 Integration Points + §3 Module 4 + §7 Known Risks (cycles/ordering/types).
2. **Check dependencies** — TASK-1523/1524/1525 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `_detect_circular_dependencies` and confirm the
   `_collect_fields`/`iter_fields` helpers before editing.
4. **Update index** → `"in-progress"`.
5. **Implement** the rule-integrity pass + extended cycle detection + wiring + tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Added validate_rules() method for reference/ordering/type-compat checks, _validate_operation() helper, and extended _detect_circular_dependencies() to include post_depends and operation edges. Wired validate_rules into validate(). check_schema() now also calls validate_rules. 17 tests pass.

**Deviations from spec**: none
