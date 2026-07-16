---
type: Wiki Overview
title: 'TASK-1580: FormSchema.is_public field'
id: doc:sdd-tasks-completed-task-1580-formschema-is-public-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Module 4 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).
---

# TASK-1580: FormSchema.is_public field

**Feature**: FEAT-241 — FormDesigner Public Forms
**Spec**: `sdd/specs/formdesigner-public-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements Module 4 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).
It is the foundational data-model change: add `is_public: bool = False` to `FormSchema`
so all downstream modules (M5, M6, M7) can reference it.

`FormSchema` has NO `is_public` field today (verified: schema.py:267-315). This task
adds the field and verifies it round-trips through the existing persistence layer
and extractors without breakage.

---

## Scope

- Add `is_public: bool = False` to `FormSchema` (after `published_version`, before validators).
- Verify the field appears in `model_fields` and round-trips via `.model_dump()` / `.model_validate()`.
- Add a docstring entry for the new field in `FormSchema`'s class docstring (mirroring the style of existing fields).
- Write unit tests in `packages/parrot-formdesigner/tests/unit/core/test_formschema_is_public.py`.

**NOT in scope**: lifecycle toggle logic (M6/TASK-1582); public-path helper (M5/TASK-1581);
exclude-provider registration (M7/TASK-1583).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | Add `is_public: bool = False` to `FormSchema` |
| `packages/parrot-formdesigner/tests/unit/core/test_formschema_is_public.py` | CREATE | Unit tests for the new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
from pydantic import BaseModel  # verified: schema.py uses Pydantic v2 BaseModel
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py

class FormSchema(BaseModel):  # line 267
    """FormSchema is the central data model of the forms abstraction layer.

    Attributes:
        form_id: Unique identifier for this form.   # line 275
        ...
    """
    form_id: str                            # line 300
    form_type: FormType = FormType.SIMPLE  # line 313
    published_version: str | None = None   # line 315
    # INSERT: is_public: bool = False  — after published_version
    # ... validators follow at line 323
```

### Does NOT Exist
- ~~`FormSchema.is_public`~~ — **to be created by this task**; grep confirms zero occurrences today
- ~~`FormSchema.public`~~ — not a field; do not create this alias
- ~~`FormSchema.is_anonymous`~~ — not a field
- ~~Any migration machinery~~ — Pydantic field defaults handle backward compat automatically
  (old serialized forms without `is_public` will deserialize to `False`)

---

## Implementation Notes

### Where to Insert

Add AFTER `published_version` (line 315), before the `@model_validator` at line 323:

```python
    published_version: str | None = None   # line 315
    is_public: bool = False                # NEW — FEAT-241: anonymous access to this form's public URLs
```

Also add a docstring line for `is_public` in the class docstring where other attributes are described:
```
    is_public: If True, the form's read and submission URLs are accessible without authentication.
               Default False. Toggling to True registers the form's public paths in
               navigator-auth's runtime exclude list; toggling to False unregisters them.
```

### Key Constraints
- Use `bool = False` (not `Optional[bool]`, not `bool | None`) — always a boolean.
- Do NOT add `Field(...)` with extra validators — plain default is sufficient.
- The field must survive Pydantic `model_dump()` / `model_validate()` round-trips including
  JSON round-trips (`model_dump(mode="json")` / `model_validate_json(...)`).
- Existing `FormSchema` instances constructed without `is_public=` must work (default applies).

---

## Acceptance Criteria

- [ ] `FormSchema(form_id="x", title="y", sections=[])` creates an instance with `is_public=False`.
- [ ] `FormSchema(form_id="x", title="y", sections=[], is_public=True).is_public is True`.
- [ ] `schema.model_dump()` contains `"is_public": False` (or True).
- [ ] `FormSchema.model_validate({"form_id": "x", ..., "is_public": True})` works.
- [ ] A serialized form dict WITHOUT `"is_public"` round-trips to `is_public=False` (backward compat).
- [ ] All existing tests still pass: `pytest packages/parrot-formdesigner/tests/ -v`.
- [ ] New tests pass: `pytest packages/parrot-formdesigner/tests/unit/core/test_formschema_is_public.py -v`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` passes.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/core/test_formschema_is_public.py
import pytest
from parrot_formdesigner.core.schema import FormSchema


@pytest.fixture
def minimal_schema_kwargs():
    """Minimal kwargs to construct a valid FormSchema."""
    return {"form_id": "test-form", "title": "Test Form", "sections": []}


class TestFormSchemaIsPublicField:
    def test_default_is_false(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs)
        assert schema.is_public is False

    def test_can_set_true(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs, is_public=True)
        assert schema.is_public is True

    def test_round_trips_model_dump(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs, is_public=True)
        data = schema.model_dump()
        assert "is_public" in data
        assert data["is_public"] is True

    def test_round_trips_model_validate(self, minimal_schema_kwargs):
        data = {**minimal_schema_kwargs, "is_public": True}
        schema = FormSchema.model_validate(data)
        assert schema.is_public is True

    def test_backward_compat_missing_is_public(self, minimal_schema_kwargs):
        """Old serialized forms without is_public must default to False."""
        schema = FormSchema.model_validate(minimal_schema_kwargs)
        assert schema.is_public is False

    def test_json_round_trip(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs, is_public=True)
        json_str = schema.model_dump_json()
        restored = FormSchema.model_validate_json(json_str)
        assert restored.is_public is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-public-forms.spec.md` for full context.
2. **No dependencies** — this task can start immediately.
3. **Verify Codebase Contract**:
   - Read `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` lines 267-325
     to confirm `FormSchema` structure and find the exact insertion point after `published_version`.
   - Run `grep -rn "is_public" packages/parrot-formdesigner/` to confirm zero occurrences today.
4. **Implement** by adding `is_public: bool = False` after `published_version`.
5. **Run existing tests** to check no regressions: `source .venv/bin/activate && pytest packages/parrot-formdesigner/tests/ -x -q`.
6. **Run new tests**: `pytest packages/parrot-formdesigner/tests/unit/core/test_formschema_is_public.py -v`.
7. **Commit in the feature worktree** (this repo, NOT navigator-auth):
   `git add packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py packages/parrot-formdesigner/tests/unit/core/test_formschema_is_public.py`

---

## Completion Note

<<<<<<< HEAD
*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
=======
**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-16
**Notes**: Added `is_public: bool = False` to `FormSchema` after `published_version`.
Updated class docstring. All 10 unit tests pass with `PYTHONPATH` pointing to
worktree source (the editable install resolves from main repo; worktree tests run
correctly with PYTHONPATH override).

**Deviations from spec**: none
>>>>>>> feat-241-formdesigner-public-forms
