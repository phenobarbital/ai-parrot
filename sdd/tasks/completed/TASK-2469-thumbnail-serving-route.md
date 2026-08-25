# TASK-2469: Thumbnail Serving Route

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2444, TASK-2445, TASK-2446
**Assigned-to**: unassigned

---

## Context

Follow-up from FEAT-460's adversarial code review (raised against
TASK-2445's implementation): `FileEnvelope.thumbnail_url` is documented as
"URL to a server-generated thumbnail" and the spec's own
`sample_image_envelope` fixture (§4) shows a real HTTP path
(`"/api/v1/test-tenant/forms/form-uid/fields/field-uid/thumbnail/thumb-uuid"`),
but the shipped implementation (`api/file_upload.py::_finalize_envelope`)
currently populates `thumbnail_url` with the raw blob reference returned by
`ThumbnailService.generate()` (e.g. `"temp://form-uid/field-uid/uuid"`) —
not a URL any frontend can actually `GET`. No thumbnail-serving route
exists anywhere in `api/routes.py`. This task closes that gap: register a
route that streams thumbnail bytes back, and change `thumbnail_url` to
point at it.

---

## Scope

- Add `handle_get_thumbnail` in `api/file_upload.py`:
  - Resolve `form_uid`/`field_uid` from the path, tenant via
    `declared_tenant`, and the field via `find_field_by_uid` (mirrors
    `handle_file_upload`'s resolution block) — 404 if form/field not found
    or the field is not an upload type.
  - Accept the thumbnail's opaque `blob_ref` as a URL-encoded query
    parameter (`?ref=...`) — blob_ref strings are backend-opaque
    (`temp://...`, `s3://bucket/...`, `gs://...`) and contain `/`, so a
    query param avoids re-deriving/parsing a backend-specific key shape
    from a path segment.
  - Stream the thumbnail via `AbstractBlobStorage.get(ref)` (remember:
    `get()` is `async def` and RETURNS an async iterator — must be
    awaited once, then iterated; see TASK-2451's completion note for the
    exact bug this caused in the chunked-upload path) and return
    `web.StreamResponse` (or a buffered `web.Response`) with
    `content_type="image/webp"` (`ThumbnailService`'s only output format
    today).
  - 404 if `blob_storage.get(ref)` raises (missing/expired blob) —
    catch narrowly, do not let a storage-backend exception surface as 500.
- Register `GET .../forms/{form_uid}/fields/{field_uid}/thumbnail` in
  `setup_form_api` (`api/routes.py`), wrapped with `_wrap_auth` (default
  `tenant="required"`, same as the `/file-upload` route it sits next to).
- Update `_finalize_envelope` in `api/file_upload.py`: build the actual
  URL (`f"{tp}/forms/{form.form_uid}/fields/{field.field_uid}/thumbnail?ref={quote(thumb_ref, safe='')}"`)
  instead of assigning the raw blob_ref to `thumbnail_url`. Needs the
  route's path prefix (`/api/v1/{tenant}`) — either pass it in from the
  caller (`handle_file_upload` already has `request` and can build the
  prefix from `request.path`/`declared_tenant`) or thread a `base_path`
  parameter through; pick whichever keeps `_finalize_envelope`'s
  signature simplest.
- Write unit tests for the new route (found/not-found, correct
  `Content-Type`, correct bytes) and update TASK-2445/TASK-2451's
  existing thumbnail assertions if they now expect a URL shape instead of
  a bare blob_ref (check `test_file_upload_handler.py::test_thumbnail_for_image`
  and `test_file_upload.py::test_image_upload_with_thumbnail`).

**NOT in scope**: Changing `ThumbnailService`'s output format/dimensions,
adding a thumbnail route for anything other than the FILE/IMAGE/
IMAGE_DROPZONE/MULTI_UPLOAD pipeline, signed/expiring URLs (out of scope
per spec's Non-Goals framing — this mirrors the existing unsigned
`blob_ref` trust model).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py` | MODIFY | Add `handle_get_thumbnail`; update `_finalize_envelope` to build a URL |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Register `GET .../fields/{field_uid}/thumbnail` |
| `packages/parrot-formdesigner/tests/unit/test_file_upload_handler.py` | MODIFY | Update `thumbnail_url` assertions to the new URL shape |
| `packages/parrot-formdesigner/tests/integration/test_file_upload.py` | MODIFY | Update `thumbnail_url` assertions; add a route round-trip test |
| `packages/parrot-formdesigner/tests/unit/test_thumbnail_route.py` | CREATE | Unit tests for `handle_get_thumbnail` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.api.tenant import declared_tenant
from parrot_formdesigner.api.handlers import extract_form_uid, extract_uid
from parrot_formdesigner.core.resolution import find_field_by_uid
from parrot_formdesigner.core.file_envelope import UPLOAD_FIELD_TYPES
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage
from urllib.parse import quote, unquote
```

### Existing Signatures to Use
```python
# parrot_formdesigner/services/blob_storage.py:152
async def get(self, blob_ref: str) -> AsyncIterator[bytes]: ...
# NOTE: this is `async def` and it RETURNS an iterator — callers must
# `stream = await blob_storage.get(ref)` THEN `async for chunk in stream`.
# Getting this wrong was a real bug found by TASK-2451's chunked-upload
# integration test (see that task's completion note) — do not repeat it.

# parrot_formdesigner/api/file_upload.py (this feature, TASK-2445/2446)
def _get_blob_storage(app: web.Application) -> AbstractBlobStorage: ...
async def _finalize_envelope(
    file_bytes: bytes, filename: str, content_type: str, checksum_hex: str,
    app: web.Application, form: FormSchema, field: FormField,
    blob_storage: AbstractBlobStorage, blob_tenant: str | None, max_inline: int,
) -> FileEnvelope: ...
    # Currently: `thumbnail_url = await thumbnail_service.generate(...)`
    # assigns the raw blob_ref directly — THIS is the line to change.

# parrot_formdesigner/api/routes.py — route registration pattern (added by
# TASK-2446, sits right after the REST upload route):
app.router.add_post(
    f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/file-upload",
    _wrap_auth(file_upload_module.handle_file_upload),
)
```

### Does NOT Exist
- ~~`handle_get_thumbnail`~~ — does not exist yet; this task creates it
- ~~`GET .../thumbnail` route~~ — not registered yet
- ~~`AbstractBlobStorage.get_url()`~~ — no such method; every backend only
  exposes `get()` (stream bytes), never a signed/direct URL
- ~~A `thumbnail_ref` field on `FileEnvelope`~~ — not part of this task;
  `thumbnail_url` is repurposed to hold the real URL, the model itself
  (`core/file_envelope.py`) is unchanged

---

## Acceptance Criteria

- [ ] `GET .../forms/{form_uid}/fields/{field_uid}/thumbnail?ref=<encoded-blob-ref>` returns the thumbnail bytes with `Content-Type: image/webp`
- [ ] Returns 404 for an unknown/expired `ref`, an unknown form/field, or a non-upload field type
- [ ] `FileEnvelope.thumbnail_url` in the `/file-upload` response is now a fetchable path under this route (not a bare blob_ref)
- [ ] Round-trip: upload an image via `/file-upload`, then `GET` the returned `thumbnail_url` and get back valid image bytes
- [ ] Existing thumbnail tests (TASK-2445/2451) updated and passing
- [ ] No regression to non-thumbnail upload flows

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2444, TASK-2445, TASK-2446 are completed
3. **Verify the Codebase Contract** — re-confirm `_finalize_envelope`'s current signature and the `get()` await-then-iterate pattern before touching either
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the route + `_finalize_envelope` URL change
6. **Update** the existing thumbnail assertions in TASK-2445/2451's test files
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2469-thumbnail-serving-route.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
