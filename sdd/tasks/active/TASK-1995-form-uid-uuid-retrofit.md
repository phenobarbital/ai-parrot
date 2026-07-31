# TASK-1995: form_uid str → uuid.UUID retrofit

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none — but HARD GATE: FEAT-389 (form-uid-stable-identity) must be merged to `dev` before starting
**Assigned-to**: unassigned

---

## Context

Implements Module 1 of FEAT-393 (spec §3, blueprint §9). FEAT-389 ships
`form_uid` as `str`; this feature standardizes ALL identity fields on
`uuid.UUID`. This task converts `form_uid` everywhere it appears so later
tasks add `field_uid`/`section_uid`/`subsection_uid` with a consistent type.

---

## Scope

- Change `FormSchema.form_uid`, `FormSubmission.form_uid`,
  `BlobMetadata.form_uid` from `str` to `uuid.UUID` with
  `Field(default_factory=uuid.uuid4)`.
- Update `extract_form_uid()` to return `uuid.UUID` (parse via
  `uuid.UUID(raw)`, `HTTPBadRequest` on `ValueError`).
- `FormRegistry`: primary dict keys and `_slug_index` values become
  `uuid.UUID`.
- `PostgresFormStorage` / `FormSubmissionStorage`: bind `uuid.UUID` natively
  via asyncpg; drop `str(...)` conversions at the SQL boundary (column type
  migration itself is TASK-2008).
- Update `CreateFormTool` form_uid generation/injection to `uuid.UUID`.
- Update existing FEAT-389 tests for the type change; assert JSON wire shape
  is unchanged (UUID serializes to canonical string).

**NOT in scope**: field/section/subsection UIDs (TASK-1996); DDL migrations
(TASK-2008).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `FormSchema.form_uid` type |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | MODIFY | UUID dict keys, slug index values |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` | MODIFY | SQL param binding |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` | MODIFY | `FormSubmission.form_uid` type |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py` | MODIFY | `BlobMetadata.form_uid` type |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `extract_form_uid` return type |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | UUID generation |
| `packages/parrot-formdesigner/tests/` | MODIFY | type-change fallout |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL — every anchor below predates the FEAT-389 merge and WILL
> shift.** First action of this task: re-verify each anchor on the merged
> `dev` (grep for `form_uid`) and update this contract before editing.

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema  # core/schema.py (FormSchema ~:260)
from parrot_formdesigner.services.blob_storage import BlobMetadata  # :55-74
```

### Existing Signatures to Use
```python
# Pre-FEAT-389 state (dev@94d8fc543) — FEAT-389 ADDS form_uid to these:
# core/schema.py:305  form_id: str  (FormSchema; form_uid lands next to it)
# FEAT-389 spec shape (sdd/specs/form-uid-stable-identity.spec.md):
#   form_uid: str = Field(default_factory=lambda: str(uuid.uuid4()))
# TARGET shape (this task):
#   form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)
# FEAT-389 also adds: FormRegistry.get(form_uid), get_by_slug(), list_form_uids(),
#   extract_form_uid(request) -> str, PostgresFormStorage UNIQUE(form_uid, version)
```

### Does NOT Exist
- ~~`FormSchema.form_uid` on pre-FEAT-389 dev~~ — only exists after the merge; do not start before it
- ~~`FormField.field_uid`~~ — created in TASK-1996, not here
- ~~custom UUID serializers~~ — not needed; Pydantic v2 serializes UUID → str natively

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 1" blueprint is authoritative:
```python
form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)

def extract_form_uid(request: web.Request) -> uuid.UUID:
    raw = request.match_info["form_uid"]
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise web.HTTPBadRequest(reason=f"invalid form_uid: {raw!r}")
```

### Key Constraints
- asyncpg binds `uuid.UUID` natively to `UUID` columns; until TASK-2008
  migrates column types (VARCHAR(36) → UUID), pass `str(form_uid)` at the SQL
  boundary and leave a `# TASK-2008` marker at each conversion site.
- JSON wire shape must NOT change — add an explicit round-trip test.
- Registry keys: `uuid.UUID` is hashable — key dicts on it directly.

### References in Codebase
- `sdd/specs/form-uid-stable-identity.spec.md` — FEAT-389 module breakdown (what merged)
- `sdd/specs/formdesigner-field-uid.spec.md` §9 Module 1

---

## Acceptance Criteria

- [ ] All `form_uid` model fields are `uuid.UUID`; no `str(uuid.uuid4())` default factories remain
- [ ] `extract_form_uid` returns `uuid.UUID`; invalid UUID → 400
- [ ] JSON responses serialize `form_uid` as canonical UUID string (round-trip test)
- [ ] Full formdesigner suite passes: `pytest packages/parrot-formdesigner/tests/ -v`
- [ ] `ruff check packages/parrot-formdesigner/src/`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/core/test_form_uid_type.py
import uuid
from parrot_formdesigner.core.schema import FormSchema

def test_form_uid_is_uuid_type(minimal_form_kwargs):
    form = FormSchema(**minimal_form_kwargs)
    assert isinstance(form.form_uid, uuid.UUID)

def test_form_uid_json_roundtrip(minimal_form_kwargs):
    form = FormSchema(**minimal_form_kwargs)
    dumped = form.model_dump_json()
    restored = FormSchema.model_validate_json(dumped)
    assert restored.form_uid == form.form_uid  # wire shape: canonical string

def test_client_supplied_form_uid_accepted(minimal_form_kwargs):
    uid = uuid.uuid4()
    form = FormSchema(form_uid=str(uid), **minimal_form_kwargs)
    assert form.form_uid == uid
```

---

## Agent Instructions

When you pick up this task:

1. **Verify the gate**: `grep -n "form_uid" packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` — if empty, FEAT-389 is NOT merged: STOP and report.
2. **Read the spec** §9 Module 1 and re-verify every contract anchor on merged dev.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
