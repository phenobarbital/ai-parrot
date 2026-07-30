# TASK-1972: Add form_uid field to FormSchema

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task. All other tasks depend on `FormSchema` having a
`form_uid` field. Implements Module 1 from the spec.

---

## Scope

- Add `form_uid: str = Field(default_factory=lambda: str(uuid.uuid4()))` to
  `FormSchema`, positioned as the FIRST field (before `form_id`).
- Add `import uuid` if not already present in the module.
- Ensure `form_uid` is included in serialization (`model_dump()`, `model_dump_json()`).
- Verify that existing `FormSchema` instantiation (without explicit `form_uid`) still
  works — the default factory auto-generates.

**NOT in scope**: Changing FormRegistry, API routes, storage, or any consumer of FormSchema.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | Add `form_uid` field to `FormSchema` |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | Add tests for `form_uid` auto-generation (CORRECTED 2026-07-30: `tests/test_schema.py` does not exist; `tests/unit/test_core_models.py` is the actual, existing `FormSchema` test file — verified via find) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# CORRECTED (2026-07-30): core/schema.py currently imports
# `from pydantic import BaseModel, ConfigDict, model_validator` — `Field` is
# NOT already imported anywhere in the file (verified via grep). Must add
# `Field` to that import line. `import uuid` is also not present — must add.
from pydantic import BaseModel, ConfigDict, Field, model_validator
import uuid  # stdlib — add to core/schema.py
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:267
class FormSchema(BaseModel):
    form_id: str                                # line 305
    version: str = "1.0"                        # line 306
    title: LocalizedString                      # line 307
    # ... (see spec §6 for full listing)
```

### Does NOT Exist
- ~~`FormSchema.form_uid`~~ — does not exist yet. This task creates it.
- ~~`FormSchema.uid`~~ — does not exist. The field must be named `form_uid`.

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the same pattern as FormSubmission.submission_id (submissions.py:86)
class FormSchema(BaseModel):
    form_uid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_id: str
    # ... rest unchanged
```

### Key Constraints
- `form_uid` must come BEFORE `form_id` in the field declaration order.
- Use `str` type (not `uuid.UUID`) for JSON serialization simplicity — consistent
  with `FormSubmission.submission_id` pattern.
- Do NOT add any validator that mutates `form_uid` — it must be immutable after creation.

---

## Acceptance Criteria

- [ ] `FormSchema` has `form_uid: str` field with UUID4 default factory
- [ ] Creating `FormSchema(form_id="test", title="Test", sections=[...])` auto-generates `form_uid`
- [ ] Providing explicit `form_uid` is respected (no override)
- [ ] `model_dump()` includes `form_uid`
- [ ] Existing tests still pass: `pytest packages/parrot-formdesigner/tests/ -v`

---

## Test Specification

```python
import uuid
from parrot_formdesigner.core.schema import FormSchema, FormSection

class TestFormSchemaFormUid:
    def test_auto_generated(self):
        form = FormSchema(
            form_id="test",
            title="Test",
            sections=[FormSection(section_id="s1", title="S1", fields=[])],
        )
        assert form.form_uid is not None
        uuid.UUID(form.form_uid)  # validates UUID format

    def test_explicit_uid_respected(self):
        uid = str(uuid.uuid4())
        form = FormSchema(
            form_uid=uid,
            form_id="test",
            title="Test",
            sections=[FormSection(section_id="s1", title="S1", fields=[])],
        )
        assert form.form_uid == uid

    def test_unique_per_instance(self):
        f1 = FormSchema(form_id="a", title="A", sections=[])
        f2 = FormSchema(form_id="b", title="B", sections=[])
        assert f1.form_uid != f2.form_uid

    def test_included_in_dump(self):
        form = FormSchema(form_id="t", title="T", sections=[])
        data = form.model_dump()
        assert "form_uid" in data
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-uid-stable-identity.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `FormSchema` at `core/schema.py:267`
4. **Implement** the `form_uid` field addition
5. **Run tests**: `pytest packages/parrot-formdesigner/tests/ -v`
6. **Update status** in per-spec index → `"in-progress"` then `"done"`
7. **Move this file** to `sdd/tasks/completed/`

---

## Completion Note

Implemented as specified. Added `import uuid` and `Field` to the pydantic
import in `core/schema.py`, and added `form_uid: str =
Field(default_factory=lambda: str(uuid.uuid4()))` as the first field on
`FormSchema` (before `form_id`), plus a docstring entry.

**Codebase Contract correction**: the contract's "Verified Imports" and
"Files to Create/Modify" were stale — `Field` was not actually imported in
`core/schema.py` (only `BaseModel, ConfigDict, model_validator`), and
`tests/test_schema.py` does not exist (the real `FormSchema` test file is
`tests/unit/test_core_models.py`). Corrected both sections in this file
before implementing, per the Codebase Contract verification step.

Added `TestFormSchemaFormUid` test class to `tests/unit/test_core_models.py`
covering: auto-generation, explicit-uid respect, uniqueness per instance,
inclusion in `model_dump()`, and immutability on `form_id` rename — matching
the task's Test Specification plus one extra (immutability) directly from
the spec's acceptance criteria.

**Test note**: worktrees share the main repo's `.venv`, whose editable
install of `parrot_formdesigner` resolves to the main repo's `src/`, not
the worktree's. Tests were run with
`PYTHONPATH="<worktree>/packages/parrot-formdesigner/src:$PYTHONPATH"`
prepended to pick up the worktree's copy of `schema.py`.

All 5 new tests pass. One pre-existing, unrelated failure
(`test_field_type_enum_total_count`, expects 32 `FieldType` values but
finds 33) was confirmed via `git stash` to predate this change — out of
scope, not touched.
