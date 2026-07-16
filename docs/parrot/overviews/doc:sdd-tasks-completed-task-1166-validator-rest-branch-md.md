---
type: Wiki Overview
title: 'TASK-1166: `FormValidator` branch for `FieldType.REST`'
id: doc:sdd-tasks-completed-task-1166-validator-rest-branch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'of a `FieldType.REST` answer: `{answer, blob_ref, status?}`, rejecting'
---

# TASK-1166: `FormValidator` branch for `FieldType.REST`

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 7)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1162, TASK-1163
**Assigned-to**: unassigned

---

## Context

`FormValidator.validate_field` already has a dispatch ladder for each
`FieldType`. This task adds one branch enforcing the submit-time shape
of a `FieldType.REST` answer: `{answer, blob_ref, status?}`, rejecting
`status == "in_progress"` and (when `field.required`) null answers.
Also surfaces `RestFieldSpec` parse errors at design time.

---

## Scope

- In `services/validators.py`, add a branch (following the existing
  pattern at lines 158, 200, 247, 257, 261) that fires when
  `field.field_type == FieldType.REST`:
  - Coerce the submitted value to a dict; reject any other shape.
  - If `status == "in_progress"` → structured error
    `{field_id, status: "in_progress"}` (a custom validator error
    shape — mirror the existing `RemoteResponse`-style rejection).
  - If `field.required and (answer is None or "answer" not in value)`
    → invalid.
  - Strip the `status` field from valid values before they reach
    storage (validators return / mutate the coerced value — match
    existing conventions in this file).
  - Parse `field.meta["rest"]` via `RestFieldSpec.model_validate` at
    design time (in `validate_form` or its equivalent caller) and
    surface any `ValidationError` as a designer-facing error.
- Unit tests for shape-accept, required-rejects-null, status-in-progress
  rejection, and `RestFieldSpec` round-trip.

**NOT in scope**: MIME / size validation (those reuse existing
`FieldConstraints` checks; no new code).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | +1 branch |
| `packages/parrot-formdesigner/tests/unit/services/test_validators_rest.py` | CREATE | Branch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
# Field-type dispatch (existing pattern):
# line 158:  if field.field_type == FieldType.REMOTE_RESPONSE:
# line 200:  if field.field_type == FieldType.REMOTE_RESPONSE:
# line 247:  if c.allowed_mime_types and field.field_type in (FILE, IMAGE):
# line 257:  if field.options and field.field_type == FieldType.SELECT:
# line 261:  elif field.options and field.field_type == FieldType.MULTI_SELECT:
# line 303:  FieldType.TEXT, TEXT_AREA, EMAIL, ...

# Mirror the REMOTE_RESPONSE branch at 158/200 for shape + design-time
# parse. Mirror 247 for the constraints reuse (no changes needed — the
# REST type lands inside the existing FILE/IMAGE-style MIME check
# automatically once you add REST to the relevant set, but ONLY if
# the existing test fixtures expect it; verify before extending).
```

### Verified Imports for the new branch

```python
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.rest_field_resolver import RestFieldSpec
```

### Does NOT Exist

- ~~A `FieldType.REST` branch in `validators.py`~~ — added by this task.
- ~~A separate `RestSubmissionPayload` model~~ — use a plain dict
  coercion + manual key checks to match the existing validator style.

---

## Implementation Notes

### Branch structure (sketch)

```python
if field.field_type == FieldType.REST:
    if not isinstance(value, dict):
        raise ValidationError(field_id=field.field_id, ...)
    if value.get("status") == "in_progress":
        raise ValidationError(
            field_id=field.field_id, status="in_progress")
    if field.required and value.get("answer") is None:
        raise ValidationError(field_id=field.field_id, ...)
    # Strip `status` from accepted shape.
    value.pop("status", None)
    return value
```

### Design-time parse

The existing validator already has a "validate form" entry point that
walks every field. In that walker, when `field.field_type == REST`,
call `RestFieldSpec.model_validate(field.meta["rest"])` and convert
any `pydantic.ValidationError` into the validator's standard error
shape. This catches mis-typed `meta.rest` at design time, not on the
first submission.

### Key constraints

- Match the existing validator's exception/error-shape conventions
  exactly. Do NOT invent a new error model.
- Idempotent on a valid value — calling twice yields the same result.

---

## Acceptance Criteria

- [ ] Valid `{answer: 0.86, blob_ref: "s3://..."}` passes.
- [ ] `required=True` + `{answer: None, blob_ref: "..."}` raises.
- [ ] `{status: "in_progress", answer: null, blob_ref: null}` rejected with structured `{field_id, status: "in_progress"}` error.
- [ ] `meta.rest` with a typo (e.g. `mod` instead of `mode`) is caught at design-time validation.
- [ ] Returned/coerced value drops the `status` key before persistence.
- [ ] No regression in existing `validators.py` tests.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.services.validators import FormValidator

@pytest.fixture
def rest_field():
    return FormField(
        field_id="x", field_type=FieldType.REST, label="x",
        required=True,
        meta={"rest": {"mode": "callback", "callback_ref": "cb"}})

def test_accepts_answer_blob_ref(rest_field):
    v = FormValidator()
    out = v.validate_field(rest_field, {"answer": 0.86, "blob_ref": "s3://x"})
    assert out["answer"] == 0.86 and "status" not in out

def test_rejects_in_progress(rest_field):
    v = FormValidator()
    with pytest.raises(Exception) as ei:
        v.validate_field(rest_field, {
            "answer": None, "blob_ref": None, "status": "in_progress"})
    # error carries the in_progress signal — assert per the validator's
    # actual error model.

def test_required_rejects_null_answer(rest_field):
    v = FormValidator()
    with pytest.raises(Exception):
        v.validate_field(rest_field, {"answer": None, "blob_ref": None})

def test_design_time_parse_catches_typo():
    bad = FormField(field_id="x", field_type=FieldType.REST, label="x",
                    meta={"rest": {"mod": "callback"}})  # typo
    v = FormValidator()
    with pytest.raises(Exception):
        v.validate_form_schema(bad)  # or whatever the walker is named
```

---

## Completion Note

Added REST dispatch in `validate_field()`, REST coercion in `_coerce_value()`, REST handling in `validate()` sanitized_data section, and `_validate_rest_field()` method. The method validates dict shape, rejects status=="in_progress" with structured error, rejects null answer when required, strips "status" key, and performs design-time RestFieldSpec parse from meta["rest"]. Created test file `tests/unit/services/test_validators_rest.py` with 11 tests, all passing.
