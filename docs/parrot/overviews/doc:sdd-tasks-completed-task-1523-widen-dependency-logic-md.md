---
type: Wiki Overview
title: 'TASK-1523: Widen DependencyRule.logic to and|or|xor|not'
id: doc:sdd-tasks-completed-task-1523-widen-dependency-logic-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundational model change (spec §3 Module 1). `DependencyRule.logic` is currently
---

# TASK-1523: Widen DependencyRule.logic to and|or|xor|not

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundational model change (spec §3 Module 1). `DependencyRule.logic` is currently
`Literal["and", "or"]`. This feature requires `xor` and `not` as well. Every later task
(operations, post-dependencies, validation, evaluator) builds on this widened type, so it
must land first. Must remain fully backward-compatible: default stays `"and"` and existing
imported rules (`and`/`or`) are unchanged.

---

## Scope

- Widen `DependencyRule.logic` to `Literal["and", "or", "xor", "not"]` in
  `core/constraints.py` (line 168). Default remains `"and"`.
- Update the `DependencyRule` docstring to describe `xor`/`not`.
- Add unit tests proving `xor`/`not` construct and `and`/`or` still validate.

**NOT in scope**: evaluation semantics of xor/not (that lives in the `RuleEvaluator`,
TASK-1530, and the validator, TASK-1526); operations; post-dependencies; renderer changes.
Do NOT change `effect`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` | MODIFY | Widen `DependencyRule.logic` literal + docstring |
| `packages/parrot-formdesigner/tests/` (new or existing test_constraints/test_dependency module) | CREATE/MODIFY | Tests for widened logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core import DependencyRule, FieldCondition, ConditionOperator
# verified: re-exported from parrot_formdesigner/core (constraints.py)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class DependencyRule(BaseModel):                                 # line 158
    conditions: list[FieldCondition]                            # line 167
    logic: Literal["and", "or"] = "and"                         # line 168  ← change here
    effect: Literal["show","hide","require","disable"] = "show" # line 169  ← DO NOT change

class FieldCondition(BaseModel):                                # line 144
    field_id: str                                               # 153
    operator: ConditionOperator                                 # 154
    value: Any = None                                           # 155
```

### Does NOT Exist
- ~~`DependencyRule.logic == "xor"` / `"not"`~~ — only `"and"`/`"or"` today (this task adds them).
- ~~A nested boolean condition tree~~ — `conditions` is a flat `list[FieldCondition]` (out of scope; spec §1 Non-Goals).

---

## Implementation Notes

### Pattern to Follow
Pure `Literal` widening — no new model. Match the existing Pydantic v2 style in the file
(`model_config = ConfigDict(extra="forbid")` is NOT on `DependencyRule`; leave as-is).

### Key Constraints
- Default MUST remain `"and"` (backward compatibility).
- Do not introduce evaluation behavior here — this is a type/model change only.

### References in Codebase
- `core/constraints.py:158-169` — the `DependencyRule` model to edit.

---

## Acceptance Criteria

- [ ] `DependencyRule(conditions=[...], logic="xor")` and `logic="not"` construct successfully.
- [ ] `DependencyRule(conditions=[...], logic="and")` / `"or"` still construct (no regression).
- [ ] An invalid `logic` value (e.g. `"nand"`) raises a `ValidationError`.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k dependency -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py`

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core import DependencyRule, FieldCondition, ConditionOperator

def _cond():
    return FieldCondition(field_id="f1", operator=ConditionOperator.EQ, value="x")

class TestDependencyLogic:
    @pytest.mark.parametrize("logic", ["and", "or", "xor", "not"])
    def test_accepts_logic(self, logic):
        r = DependencyRule(conditions=[_cond()], logic=logic)
        assert r.logic == logic

    def test_default_logic_is_and(self):
        assert DependencyRule(conditions=[_cond()]).logic == "and"

    def test_rejects_unknown_logic(self):
        with pytest.raises(ValidationError):
            DependencyRule(conditions=[_cond()], logic="nand")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `constraints.py:168` still reads
   `logic: Literal["and", "or"] = "and"` before editing.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** the literal widening + docstring + tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Widened DependencyRule.logic Literal from "and"|"or" to "and"|"or"|"xor"|"not". Default remains "and". Forward reference to DependencyOperation added. model_rebuild() called at module level. 51 tests pass.

**Deviations from spec**: Implemented together with TASK-1524/1525 in a single code commit since all three tasks modify the same file (constraints.py). Tests cover all three model-layer tasks in one test file.
