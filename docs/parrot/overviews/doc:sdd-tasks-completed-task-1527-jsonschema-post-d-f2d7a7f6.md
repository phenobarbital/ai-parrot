---
type: Wiki Overview
title: 'TASK-1527: JsonSchemaRenderer emits x-post-depends + serialized operations'
id: doc:sdd-tasks-completed-task-1527-jsonschema-post-depends-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5. The JSON Schema renderer already serializes pre-dependencies
  as `x-depends-on`.
---

# TASK-1527: JsonSchemaRenderer emits x-post-depends + serialized operations

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1523, TASK-1524, TASK-1525
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The JSON Schema renderer already serializes pre-dependencies as `x-depends-on`.
This task adds `x-post-depends` (and serialized `operations`) so the new forward-effect/operation
declarations reach clients as hints. Existing `x-depends-on` output must stay byte-stable.

---

## Scope

- In `renderers/jsonschema.py`, where `prop["x-depends-on"] = field.depends_on.model_dump()` is set
  (line 411), also emit `prop["x-post-depends"] = [p.model_dump() for p in field.post_depends]`
  when `field.post_depends` is present.
- Ensure `operations` carried on `depends_on` are serialized within the existing `x-depends-on`
  dump (they will be, via `model_dump()` — add a test asserting it).
- Update the renderer module docstring (jsonschema.py:122 lists the `x-` keys) to document
  `x-post-depends`.
- Unit tests: emission present/absent; legacy `x-depends-on` unchanged.

**NOT in scope**: other renderers (html5/adaptivecard/telegram/pdf/xforms/audio) — they treat the
new declarations as pass-through hints in v1 (spec §8 default); model changes; validation;
evaluation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | Emit `x-post-depends`; doc update |
| `packages/parrot-formdesigner/tests/` | CREATE/MODIFY | Renderer tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.renderers import JsonSchemaRenderer
from parrot_formdesigner.core import FormField, FieldType, DependencyRule, PostDependency, DependencyOperation
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py
#   module docstring lists x- keys, including:
#   - x-depends-on: conditional visibility rule (serialized DependencyRule)   # line 122
#   ...
#   prop["x-depends-on"] = field.depends_on.model_dump()                      # line 411  ← add x-post-depends nearby

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):
    depends_on: DependencyRule | None = None          # line 61
    post_depends: list[PostDependency] | None = None  # added in TASK-1525
```

### Does NOT Exist
- ~~`x-post-depends`~~ — not emitted today; only the `x-depends-on` family exists.
- ~~A renderer-side evaluator~~ — the renderer only serializes; it does not resolve/compute.
- ~~`field.post_depends` in any other renderer~~ — out of scope for v1.

---

## Implementation Notes

### Pattern to Follow
```python
if field.depends_on:
    prop["x-depends-on"] = field.depends_on.model_dump()
if field.post_depends:
    prop["x-post-depends"] = [p.model_dump() for p in field.post_depends]
```
Match the existing `AbstractFormRenderer.render` async signature and the renderer's existing
serialization flow.

### Key Constraints
- Do not alter existing `x-depends-on` output (assert byte-stability in a test).
- Only emit `x-post-depends` when non-empty.

### References in Codebase
- `renderers/jsonschema.py:122` (docstring), `:411` (emission point).
- `renderers/base.py` — `AbstractFormRenderer.render` signature.

---

## Acceptance Criteria

- [ ] A field with `post_depends` renders an `x-post-depends` list of serialized post-dependencies.
- [ ] A field without `post_depends` produces NO `x-post-depends` key.
- [ ] `operations` on `depends_on` appear inside the `x-depends-on` dump.
- [ ] Existing `x-depends-on` output is unchanged for a legacy field (regression test).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k jsonschema -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.renderers import JsonSchemaRenderer
from parrot_formdesigner.core import (
    FormSchema, FormSection, FormField, FieldType,
    PostDependency, DependencyOperation, DependencyRule, FieldCondition, ConditionOperator,
)

class TestJsonSchemaPostDepends:
    async def test_emits_x_post_depends(self):
        ...  # field with post_depends → "x-post-depends" in rendered prop

    async def test_no_post_depends_key_when_absent(self):
        ...

    async def test_legacy_x_depends_on_unchanged(self):
        ...  # depends_on-only field renders identical x-depends-on as before
```

---

## Agent Instructions

1. **Read the spec** §3 Module 5 + §8 (renderer scope default).
2. **Check dependencies** — TASK-1523/1524/1525 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm jsonschema.py:411 emission point before editing.
4. **Update index** → `"in-progress"`.
5. **Implement** emission + doc + tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Added x-post-depends emission in _field_to_property() after x-depends-on. Updated module docstring listing x- keys. Legacy x-depends-on output unchanged. 7 tests pass.

**Deviations from spec**: none
