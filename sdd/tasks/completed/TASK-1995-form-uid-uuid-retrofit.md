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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**:

- Verified the FEAT-389 gate: `form_uid` existed as `str` in
  `core/schema.py` on the merged worktree before starting; re-verified every
  Codebase Contract anchor by grep (all had shifted from the pre-merge
  anchors, as warned) before editing.
- Retrofitted `form_uid` from `str` to `uuid.UUID` (`Field(default_factory=
  uuid.uuid4)`) in `FormSchema` (`core/schema.py`), `FormSubmission`
  (`services/submissions.py`), and `BlobMetadata` (`services/blob_storage.py`).
- `extract_form_uid()` (`api/handlers.py`) now returns `uuid.UUID`, raising
  `HTTPBadRequest` on parse failure (unchanged behavior otherwise).
- `FormRegistry` (`services/registry.py`): retyped the primary index
  (`_forms`), `_slug_index`, `_uid_to_slug`, and every public method taking
  or returning a form_uid (`get`, `unregister`, `clone_form`,
  `list_form_uids`, `contains`, `set_public_toggle_callback`,
  `on_unregister`) to `uuid.UUID`. Fixed a real bug found along the way:
  `clone_form()` did `clone.form_uid = str(uuid.uuid4())` via direct
  attribute assignment (`FormSchema` has no `validate_assignment`), which
  would have silently left `form_uid` as a plain `str` on every cloned form.
- `PostgresFormStorage` (`services/storage.py`): `load()`/`delete()` now
  take `uuid.UUID`; since the DB column is still `VARCHAR(36)` until
  TASK-2008's migration, every SQL boundary call explicitly does
  `str(form_uid)` with a `# TASK-2008` marker comment, per the task's own
  guidance.
- `CreateFormTool` (`tools/create_form.py`): `CreateFormInput.form_uid` /
  `refine_form_uid` and the internal `_execute`/`_generate_with_retry`
  parameters are now `uuid.UUID | None`; `effective_form_uid = form_uid or
  uuid.uuid4()` (was `str(uuid.uuid4())`).
- Added `packages/parrot-formdesigner/tests/unit/core/test_form_uid_type.py`
  (new file, within the task's `tests/` bucket) covering the type itself,
  client-supplied UUID/str values, invalid-UUID rejection, and the JSON
  wire-shape round trip (canonical string, unchanged from FEAT-389).
- Updated ~13 existing FEAT-389 test files for the type change (fixture
  literals that were not well-formed UUIDs, `== str` assertions that needed
  `str(...)` on one side, `model_copy(update=...)` calls that bypass
  Pydantic coercion, and mocked-request `match_info` helpers that must hold
  raw path **strings** exactly like real aiohttp, not `uuid.UUID` objects).

**Deviations from spec / file list**:
- Two files **outside** the task's stated "Files to Create/Modify" list
  were touched with a minimal, mechanical, type-only one-line fix each,
  because the merged suite could not pass otherwise (both are genuine
  runtime crashes caused directly by this task's `form_uid` type change,
  not pre-existing issues):
  - `renderers/html5.py` (`_inject_lifecycle`): `json.dumps(form.form_uid)`
    → `json.dumps(str(form.form_uid))` — stdlib `json` cannot serialize a
    `uuid.UUID` (unlike `JSONResponse`'s `json_encoder`, which the rest of
    the API surface already goes through).
  - `renderers/audio.py` (`AudioFormRenderer.render`): `AudioFormManifest(
    form_uid=form.form_uid, ...)` → `form_uid=str(form.form_uid)` —
    `AudioFormManifest.form_uid` is a wire-facing `str` field
    (`audio/models.py`), left untouched (out of TASK-1995's scope; that
    model belongs to Module 10 / TASK-2004).
  - Flagging both explicitly per Cardinal Rule 4 rather than silently
    expanding scope. No other files were touched beyond the stated list
    and `tests/`.
- `api/uploads.py`, `api/audio_ws.py`, `renderers/telegram/*`,
  `services/form_version.py`, `services/public_forms.py`,
  `ui/templates.py` still type-hint `form_uid: str` (stale) but were
  verified NOT to break at runtime (either they read the raw
  `request.match_info` string directly without going through
  `extract_form_uid()`, or Python's lack of runtime type enforcement means
  they keep working transparently once the value flows through
  consistently). Left untouched — correcting their type hints belongs to
  the modules that own them (TASK-1999/2002/2008 etc.), per file fidelity.

**Verification**:
- `pytest packages/parrot-formdesigner/tests/ -v` → 1760 passed, 3 skipped,
  20 failed. Verified via `git stash` that the same 20 failures are 100%
  pre-existing and unrelated to this task (control-registry counts, field
  type enum counts, venue_service, msteams import, edit_toolkit tool
  counts) — identical failure set before and after this task's diff.
- `ruff check packages/parrot-formdesigner/src/` → 332 pre-existing
  findings; diffed ruff output on every file this task touched
  (before/after via `git stash`) — byte-identical, confirming zero new
  lint findings introduced.
- `from parrot.forms import FormField, FormSchema` (the ai-parrot legacy
  shim) still imports and round-trips `form_uid` as `uuid.UUID` correctly.
