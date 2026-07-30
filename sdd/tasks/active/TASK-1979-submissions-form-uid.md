# TASK-1979: Submissions add form_uid

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1972
**Assigned-to**: unassigned

---

## Context

The `FormSubmission` model and its storage DDL track which form a submission
belongs to via `form_id` (slug). Since slugs can be renamed, submissions must
also carry `form_uid` (immutable UUID) to maintain a stable link to the parent
form across renames. Implements Module 7 from the spec.

---

## Scope

- Add `form_uid: str` field to `FormSubmission` Pydantic model:
  - Required field (no default) — every submission must reference a form by UUID.
  - Positioned after `submission_id` and before `form_id`.
- Update `_create_table_sql` (greenfield DDL) to include
  `form_uid VARCHAR(36)` column in the `form_data` table.
- Update `_insert_sql` to include `form_uid` in the INSERT column list and
  VALUES placeholders.
- Add database index: `CREATE INDEX idx_form_data_form_uid ON form_data(form_uid)`.

**NOT in scope**: Migration of existing data (TASK-1975), API route changes
(TASK-1976), storage layer (TASK-1974).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` | MODIFY | Add `form_uid` to model, DDL, and insert query |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # verified: used in submissions.py
```

### Existing Signatures to Use
```python
# services/submissions.py:50
class FormSubmission(BaseModel):
    # submission_id: str               # line ~86
    # form_id: str                     # line 90
    # form_version: str                # line 91
    # ... other fields

# DDL at lines 168-204:
# CREATE TABLE IF NOT EXISTS form_data (
#     ...
#     form_id VARCHAR(255) NOT NULL,
#     ...
# )

# Insert SQL includes form_id in column list
```

### Does NOT Exist
- ~~`FormSubmission.form_uid`~~ — does not exist. This task adds it.
- ~~`form_uid` column in form_data DDL~~ — does not exist. This task adds it to greenfield.
- ~~`idx_form_data_form_uid` index~~ — does not exist. This task adds it.

---

## Implementation Notes

### Model change
```python
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_uid: str = Field(..., description="Immutable UUID of the parent form")
    form_id: str = Field(..., description="Human-readable form slug")
    form_version: str = Field(default="1.0")
    # ... rest unchanged
```

### DDL change (greenfield)
```sql
CREATE TABLE IF NOT EXISTS form_data (
    -- existing columns ...
    form_uid VARCHAR(36),           -- NEW: immutable reference to parent form
    form_id VARCHAR(255) NOT NULL,  -- existing: mutable slug
    -- ...
);
CREATE INDEX IF NOT EXISTS idx_form_data_form_uid ON form_data(form_uid);
```

### Insert SQL change
Add `form_uid` to both the column list and the `$N` placeholder list in
`_insert_sql`. Ensure the parameter order in the `execute()` call matches.

### Key Constraints
- `form_uid` in greenfield DDL should be nullable initially (existing rows
  may not have it). The migration (TASK-1975) handles backfill.
  However, the Pydantic model field is required — new submissions must
  always have `form_uid`.
- The `form_id` field is retained for backward compatibility and human readability.

---

## Acceptance Criteria

- [ ] `FormSubmission` model has `form_uid: str` field
- [ ] `form_uid` field is positioned before `form_id` in field order
- [ ] Greenfield DDL includes `form_uid VARCHAR(36)` column
- [ ] Insert SQL includes `form_uid` in column list and values
- [ ] Index `idx_form_data_form_uid` is created in greenfield DDL
- [ ] Existing submission creation continues to work (with `form_uid` now required)
- [ ] `FormSubmission.model_dump()` includes `form_uid`

---

## Test Specification
```python
import pytest
from parrot_formdesigner.services.submissions import FormSubmission

def test_form_submission_has_form_uid():
    """FormSubmission includes form_uid field."""
    sub = FormSubmission(
        form_uid="550e8400-e29b-41d4-a716-446655440000",
        form_id="my-form",
        form_version="1.0",
        data={"name": "test"}
    )
    assert sub.form_uid == "550e8400-e29b-41d4-a716-446655440000"

def test_form_submission_requires_form_uid():
    """FormSubmission raises validation error without form_uid."""
    with pytest.raises(Exception):  # ValidationError
        FormSubmission(form_id="my-form", form_version="1.0", data={})

def test_form_submission_serialization():
    """form_uid is included in model_dump()."""
    sub = FormSubmission(
        form_uid="550e8400-e29b-41d4-a716-446655440000",
        form_id="my-form",
        form_version="1.0",
        data={}
    )
    dumped = sub.model_dump()
    assert "form_uid" in dumped
    assert dumped["form_uid"] == "550e8400-e29b-41d4-a716-446655440000"
```

---

## Agent Instructions

1. Read this task file and the spec (Module 7).
2. Read `services/submissions.py` in full.
3. Verify TASK-1972 is complete (`FormSchema.form_uid` exists).
4. Implement all scope items.
5. Run existing tests: `pytest packages/parrot-formdesigner/tests/ -v -k submission`
6. Add new tests per test specification.
7. Commit with message: `sdd: TASK-1979 — submissions add form_uid`
8. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
