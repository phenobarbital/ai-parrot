---
type: Wiki Overview
title: 'TASK-1525: PostDependency model + FormField.post_depends attribute'
id: doc:sdd-tasks-completed-task-1525-postdependency-model-schema-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 3. Introduces forward dependencies: how a control''s answered
  value affects controls'
---

# TASK-1525: PostDependency model + FormField.post_depends attribute

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1523, TASK-1524
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Introduces forward dependencies: how a control's answered value affects controls
declared **after** it. Adds the `PostDependency` model and an optional `post_depends` list on
`FormField`. Resolved decision (spec §8): `post_depends` lives on `FormField` only for v1;
container-level (`FormSubsection`/`FormSection`) forward effects are deferred.

---

## Scope

- Add `PostDependency(BaseModel)` to `core/constraints.py` with fields (spec §2 Data Models):
  `target: str`, `effect: Literal["set","calc","reload_options","show","hide","require","cascade_clear"]`,
  `conditions: list[FieldCondition] | None = None`, `logic: Literal["and","or","xor","not"] = "and"`,
  `operation: DependencyOperation | None = None`.
- Add a Pydantic validator: `operation` is REQUIRED when `effect` in `{"set","calc"}`.
- Add `post_depends: list[PostDependency] | None = None` to `FormField` in `core/schema.py`
  (sibling of `depends_on` at line 61).
- Ensure `FormField.model_rebuild()` (schema.py:68) still resolves after the new field.
- Export `PostDependency` from `core/__init__.py`.
- Unit tests.

**NOT in scope**: validating that `target` is a *later* field or that references exist
(TASK-1526); evaluating effects (TASK-1530); renderer emission (TASK-1527); adding
`post_depends` to `FormSubsection`/`FormSection` (deferred per spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` | MODIFY | Add `PostDependency` model + validator |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | Add `FormField.post_depends`; keep `model_rebuild()` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Export `PostDependency` |
| `packages/parrot-formdesigner/tests/` | CREATE/MODIFY | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core import (
    FormField, PostDependency, DependencyOperation, FieldCondition, ConditionOperator,
)  # PostDependency is new (this task); DependencyOperation from TASK-1524
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):                          # line 24 (extra="forbid")
    field_id: str                                    # 50
    field_type: FieldType                            # 51
    depends_on: DependencyRule | None = None         # 61  ← add post_depends as sibling
    children: list[FormField] | None = None          # 62
    item_template: FormField | None = None           # 63
    meta: dict[str, Any] | None = None               # 64
# FormField.model_rebuild()                          # line 68 (MUST stay; self-referential)
# top of schema.py imports:
#   from .constraints import DependencyRule, FieldConstraints   (line 18)  ← add PostDependency here

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class FieldCondition(BaseModel)        # line 144
class DependencyRule(BaseModel)        # line 158
# DependencyOperation                  # added in TASK-1524
```

### Does NOT Exist
- ~~`PostDependency` / `FormField.post_depends`~~ — do not exist today (this task creates them).
- ~~`FormSubsection.post_depends` / `FormSection.post_depends`~~ — intentionally NOT added (deferred, spec §8).
- ~~Any forward-effect evaluation~~ — none exists; do not import/call an evaluator (TASK-1530).

---

## Implementation Notes

### Pattern to Follow
```python
class PostDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    effect: Literal["set","calc","reload_options","show","hide","require","cascade_clear"]
    conditions: list[FieldCondition] | None = None
    logic: Literal["and","or","xor","not"] = "and"
    operation: DependencyOperation | None = None

    @model_validator(mode="after")
    def _require_operation_for_set_calc(self):
        if self.effect in ("set","calc") and self.operation is None:
            raise ValueError(f"effect={self.effect!r} requires an 'operation'")
        return self
```
`FormField` uses `extra="forbid"` — adding the optional field is safe for existing payloads
(absent key → `None`). Re-run `FormField.model_rebuild()` after the edit.

### Key Constraints
- Keep `post_depends` optional, default `None` (backward compatibility).
- Forward-reference `DependencyOperation`/`FieldCondition` correctly if defined later in the file.

### References in Codebase
- `core/schema.py:24-68` — `FormField` + `model_rebuild`.
- `core/constraints.py:144-169` — `FieldCondition`/`DependencyRule` style.

---

## Acceptance Criteria

- [ ] `PostDependency` constructs for each `effect`; `set`/`calc` without `operation` raise `ValidationError`.
- [ ] `FormField(..., post_depends=[PostDependency(...)])` constructs; default `post_depends` is `None`.
- [ ] A `FormField` with NO `post_depends` still constructs (backward compatibility) and `model_rebuild` succeeds.
- [ ] `from parrot_formdesigner.core import PostDependency` works.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k post_depend -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core import FormField, FieldType, PostDependency, DependencyOperation

class TestPostDependency:
    def test_set_requires_operation(self):
        with pytest.raises(ValidationError):
            PostDependency(target="f2", effect="set")

    def test_show_effect_no_operation_ok(self):
        p = PostDependency(target="f2", effect="show")
        assert p.effect == "show"

    def test_formfield_post_depends(self):
        f = FormField(
            field_id="f1", field_type=FieldType.TEXT, label="A",
            post_depends=[PostDependency(target="f2", effect="set",
                          operation=DependencyOperation(op="copy", operands=["f1"], target="f2"))],
        )
        assert f.post_depends and f.post_depends[0].target == "f2"

    def test_formfield_without_post_depends(self):
        f = FormField(field_id="f1", field_type=FieldType.TEXT, label="A")
        assert f.post_depends is None
```

---

## Agent Instructions

1. **Read the spec** §2 Data Models + §3 Module 3 + §8 (resolved scope).
2. **Check dependencies** — TASK-1523 and TASK-1524 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before editing.
4. **Update index** → `"in-progress"`.
5. **Implement** model + validator + `FormField.post_depends` + `model_rebuild()` + export + tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: PostDependency model with 7 effects, optional conditions/logic/operation fields. model_validator enforces operation required for set/calc. FormField.post_depends added as optional list. FormField.model_rebuild() updated. Exported from core/__init__.py. 51 tests pass.

**Deviations from spec**: Implemented together with TASK-1523/1524 in a single commit.
