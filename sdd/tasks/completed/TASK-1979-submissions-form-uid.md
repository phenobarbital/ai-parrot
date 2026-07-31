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
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` | MODIFY | Add `form_uid` to model, DDL, insert query, AND read path (`_SELECT_COLUMNS`/`_row_to_submission`, `_alter_table_sql` — see Completion Note) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Sole production `FormSubmission(...)` constructor (in `submit_data()`) updated to supply the now-required `form_uid=form.form_uid`. |
| `packages/parrot-formdesigner/tests/unit/test_submissions.py` | MODIFY | Every constructor call site given `form_uid=`; added `test_form_uid_is_required`. |
| `packages/parrot-formdesigner/tests/unit/test_storage_schema_tenant.py` | MODIFY | `_submission()` helper + 2 `FormSubmission(...)` calls given `form_uid=`; positional-arg indices shifted (+1) in 2 assertions. |
| `packages/parrot-formdesigner/tests/unit/test_submission_metadata_storage.py` | MODIFY | All constructors given `form_uid=`; placeholder-count test renamed/renumbered ($20→$21); positional indices shifted (+1) throughout. |
| `packages/parrot-formdesigner/tests/unit/test_submission_revisions.py` | MODIFY | `_db_row()` fake-row helper given a `form_uid` key/param; all constructors given `form_uid=`; positional indices shifted (+1). |
| `packages/parrot-formdesigner/tests/unit/test_submission_metadata.py` | MODIFY | `_submission()` helper given `form_uid=`. |

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

Implemented as specified, plus corrections necessary once `form_uid`
became a REQUIRED field. Added `form_uid: str = Field(...)` (required, no
default) to `FormSubmission`, positioned after `submission_id` and before
`form_id` per the task's own layout instruction. `_create_table_sql`:
added `form_uid VARCHAR(36)` column and `idx_form_data_form_uid` index.
`_insert_sql`: added `form_uid` as the 2nd column/placeholder, renumbering
all subsequent `$N` placeholders. `store()`: threads `submission.form_uid`
through in the matching position.

**Necessary additions beyond the task's literal scope** (both required
once `form_uid` became mandatory on the model — documented here per the
established "note discoveries" discipline):

1. **Read path** (`_SELECT_COLUMNS`, `_row_to_submission`): NOT mentioned
   in the task's scope, but required — without it, `get_submission()`/
   `list_revisions()` would raise `ValidationError` on every read, since
   the required `form_uid` field would never be populated when
   reconstructing `FormSubmission` from a DB row. Added `form_uid` to both.

2. **`_alter_table_sql`** (legacy-table idempotent DDL, NOT mentioned in
   the task's scope): added `form_uid VARCHAR(36)` (+ its index) here too.
   Without this, a deployment relying on the app's own `initialize()`
   startup path (rather than manually running the TASK-1975 standalone
   migration scripts) would never get the column added to an existing
   `form_data` table, and `store()` would fail with an "undefined column"
   Postgres error on every submission. This does NOT duplicate TASK-1975 —
   it's the same idempotent mechanism already used for every other
   metadata column (`user_id`, `revision`, `context`, etc.); form_uid was
   simply missing from it.

3. **`api/handlers.py::submit_data()`**: the sole production caller that
   constructs `FormSubmission(...)` — updated to pass
   `form_uid=form.form_uid` (previously this call site had a comment
   explicitly deferring the field to "TASK-1979 (not this task)" — now
   resolved). Without this, every real form submission via the REST API
   would raise `ValidationError` and crash the endpoint.

4. **`api/audio_ws.py`**: found a SECOND production
   `FormSubmission(form_id=session.form_id, ...)` call site, missing
   `form_uid` — this file is TASK-1990's scope (not touched here). Added a
   note to TASK-1990's own task file (`sdd/tasks/active/TASK-1990-...md`)
   flagging that this call site now ALSO needs `form_uid=` once TASK-1990
   updates it, not just the match_info/registry.get() fixes already
   planned there. Not fixed here to avoid an uncoordinated, narrow patch
   ahead of TASK-1990's more thorough audio-session rework; the existing
   `try/except` around this construction already fails gracefully (logs a
   warning, session continues) both before and after this change — no
   worse than the pre-existing breakage from TASK-1976's route rename.

All ~70 `-k submission` tests pass across 5 test files with corrected
constructors/positional-argument indices (every INSERT-parameter-position
assertion shifted +1 to account for `form_uid` being the new 2nd column).
Full `pytest tests/unit/` and `tests/integration/` suites: zero new
failures, zero previously-broken tests fixed (this task's blast radius
was fully contained to submission-specific tests, all now green). Ruff:
identical error count (63) to baseline.
