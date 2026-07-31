---
type: Wiki Overview
title: 'TASK-1170: Upload route + `handle_rest_upload`'
id: doc:sdd-tasks-completed-task-1170-upload-route-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Phase 3 entry point. The full upload pipeline lives here:'
---

# TASK-1170: Upload route + `handle_rest_upload`

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 11)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1160, TASK-1161, TASK-1162, TASK-1163, TASK-1164, TASK-1166
**Assigned-to**: unassigned

---

## Context

Phase 3 entry point. The full upload pipeline lives here:
multipart parse → MIME/size check → `AuthContext` build →
`RestFieldResolver.resolve()` → `AbstractBlobStorage.put` →
JSONPath + Jinja2 → JSON envelope. Wrapped by navigator-auth's
`is_authenticated + user_session` (FEAT-152). Bootstrap wiring (the
`app[...]` keys) is TASK-1171.

---

## Scope

- Create `api/uploads.py` with `async def handle_rest_upload(request)`.
- In `api/routes.py`, extend `setup_form_api()` to mount the route:
  `app.router.add_post(f"{bp}/forms/{{form_id}}/fields/{{field_id}}/upload",
  _wrap_auth(uploads.handle_rest_upload))`.
- The handler:
  1. Resolves `field` via `app["form_registry"]`.
  2. Verifies `field.field_type == FieldType.REST`; otherwise 404.
  3. Parses `request.multipart()` streaming. Tracks bytes; aborts on
     `> field.constraints.max_file_size_bytes` with 413.
  4. Validates MIME against `field.constraints.allowed_mime_types`;
     415 if disallowed.
  5. Builds `AuthContext` via `FormAPIHandler._build_auth_context`.
  6. Parses `RestFieldSpec` from `field.meta["rest"]`.
  7. For previous-blob cleanup: looks up the prior `blob_ref` (header
     `X-Parrot-Prior-Blob-Ref` echoed by the frontend) and schedules
     synchronous delete *after* the new blob is durably written.
  8. Streams the body to `app["blob_storage"].put(...)`.
  9. Calls `app["rest_resolver"].resolve(spec, payload, auth_context,
     tenant)`.
  10. Returns the JSON envelope `{success, answer, raw_value,
      blob_ref, display, warnings, error}`.
- Error codes: 400 (`in_progress`, malformed multipart),
  413 (too-large), 415 (MIME), 500 (callback-not-registered surfaces
  as `success=False` with structured error body, NOT 500 — only
  unexpected exceptions become 500).
- Integration tests for happy-path remote/internal/callback modes,
  413, 415, and prior-blob deletion.

**NOT in scope**: bootstrap kwargs (TASK-1171), docs generation
(TASK-1172).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py` | CREATE | Handler |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Mount route |
| `packages/parrot-formdesigner/tests/integration/test_upload_rest.py` | CREATE | E2E |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:70
def setup_form_api(
    app, registry, *,
    client=None, submission_storage=None,
    forwarder=None, base_path="/api/v1",
) -> None: ...
# This task EXTENDS the mount list — does NOT change the signature
# (that is TASK-1171).

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:33
class FormAPIHandler:
    def _build_auth_context(self, request) -> AuthContext: ...   # line 149
    def _get_org_id(self, request) -> int | None: ...            # line 100
    def _get_programs(self, request) -> list[str]: ...           # line 128
    async def submit_data(self, request) -> web.Response: ...    # line 508

# packages/parrot-formdesigner/src/parrot_formdesigner/services/rest_field_resolver.py
class RestFieldResolver:
    async def resolve(self, spec, payload, *, auth_context=None,
                      tenant=None) -> RestFieldResult: ...
# (TASK-1162 — exists when this task runs.)

# Existing _wrap_auth helper:
# api/routes.py — find _wrap_auth (FEAT-167) and reuse exactly.

# aiohttp:
from aiohttp import web
```

### Does NOT Exist

- ~~`parrot_formdesigner.api.uploads`~~ — created here.
- ~~`POST /api/v1/forms/{form_id}/fields/{field_id}/upload`~~ — added.
- ~~`X-Parrot-Prior-Blob-Ref` header convention~~ — introduced here;
  document it in the response envelope contract comment.

---

## Implementation Notes

### Multipart streaming

`request.multipart()` is async. Stream parts to
`AbstractBlobStorage.put` via an async generator. Track bytes:

```python
async def _stream_with_limit(part, limit):
    total = 0
    while True:
        chunk = await part.read_chunk()
        if not chunk:
            break
        total += len(chunk)
        if limit and total > limit:
            raise web.HTTPRequestEntityTooLarge(...)
        yield chunk
```

### Envelope

```python
return web.json_response({
    "success": result.success,
    "answer": result.answer,
    "raw_value": result.raw_value,
    "blob_ref": blob_ref,
    "display": result.display,
    "warnings": result.warnings,    # list[str]
    "error": result.error,
})
```

### Never-500 on known errors

Map `RestFieldResult.success=False` to a 200 envelope with
`success: false` (the resolver's contract is "never raise"). 500 is
reserved for unexpected bugs.

### Key constraints

- Async I/O end-to-end. No blocking calls.
- Use `self.logger`-style logging (module-level logger here).
- Re-upload delete failure → append warning string; do NOT 500.

---

## Acceptance Criteria

- [ ] `POST /api/v1/forms/{form_id}/fields/{field_id}/upload` mounted.
- [ ] Auth wrapper from FEAT-152 applied (test asserts unauthenticated → 401).
- [ ] 413 on too-large multipart.
- [ ] 415 on disallowed MIME.
- [ ] Re-upload deletes prior blob (asserted by mocked storage).
- [ ] Callback mode invokes a registered coroutine; tenant override wins.
- [ ] Internal mode cascades inbound Bearer header into the internal call.
- [ ] Response envelope shape matches spec §7 Data Shapes row.

---

## Test Specification

Mirror spec §4 Integration Tests rows.

---

## Completion Note

Created `api/uploads.py` with `handle_rest_upload()`: multipart streaming with size limit, MIME validation (415), form/field resolution (404), RestFieldSpec TypeAdapter validation, blob storage put, prior-blob deletion via X-Parrot-Prior-Blob-Ref header (delete failure appends warning, no 500), RestFieldResolver.resolve() call, JSON envelope response. Resolver success=False maps to 200 with success:false. Mounted route in routes.py. Created integration test with 9 tests covering happy path, 404, 400, 415, delete failure, and resolver failure cases.
