# TASK-2445: File Upload Handler

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2442, TASK-2443, TASK-2444
**Assigned-to**: unassigned

---

## Context

This is the core handler for the new file-upload endpoint. It receives
multipart uploads, validates MIME types and file sizes against field
constraints, persists files to blob storage, generates thumbnails for images,
computes SHA-256 checksums, and returns FileEnvelope(s). Includes basic
chunked upload support. Implements **Module 3** from the spec.

Also extracts `_stream_with_limit` and `_build_auth_context` from
`api/uploads.py` to a shared `api/_upload_helpers.py` module.

---

## Scope

- Extract `_stream_with_limit` (line 142) and `_build_auth_context` (line 172)
  from `api/uploads.py` to a new `api/_upload_helpers.py` module. Update
  `api/uploads.py` to import from `_upload_helpers`.
- Create `parrot_formdesigner/api/file_upload.py` with `handle_file_upload`:
  - Parse multipart request, iterate over file parts
  - Validate MIME type against `constraints.allowed_mime_types` (415 on reject)
  - Enforce file size via `_stream_with_limit` against `constraints.max_file_size_bytes` (413 on reject)
  - Reject multiple file parts for single-cardinality fields (FILE, IMAGE) → 400
  - Reject non-upload field types → 404
  - Persist to blob storage via `AbstractBlobStorage.put()`
  - Generate data_url if file size ≤ max_inline_size_bytes
  - Compute SHA-256 checksum server-side
  - Generate thumbnail for image content types via `ThumbnailService.generate()`
  - Handle `X-Parrot-Prior-Blob-Ref` header: delete old blob on replacement
  - Basic chunked upload: detect `X-Parrot-Upload-Offset` / `X-Parrot-Upload-Length`
    headers, buffer chunks in blob storage, assemble on final chunk
  - Return JSON: single FileEnvelope for FILE/IMAGE, array for DROPZONE/MULTI_UPLOAD
- Write unit tests for the handler.

**NOT in scope**: Route registration (TASK-2446), validator updates (TASK-2447),
renderer updates (TASK-2448, TASK-2449).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/_upload_helpers.py` | CREATE | Extracted shared helpers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py` | MODIFY | Replace inline helpers with imports from `_upload_helpers` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py` | CREATE | `handle_file_upload` handler |
| `packages/parrot-formdesigner/tests/unit/test_file_upload_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.file_envelope import (
    FileEnvelope, UPLOAD_FIELD_TYPES, is_single_cardinality,
)  # created by TASK-2442
from parrot_formdesigner.core.constraints import (
    FieldConstraints, DEFAULT_MAX_INLINE_SIZE,
)  # extended by TASK-2443
from parrot_formdesigner.services.blob_storage import (
    AbstractBlobStorage,    # line 113
    BlobMetadata,           # line 55
)
from parrot_formdesigner.services.thumbnail import ThumbnailService  # created by TASK-2444
from parrot_formdesigner.core.resolution import find_field_by_uid    # line 170
from parrot_formdesigner.api.tenant import declared_tenant           # line 166
```

### Existing Signatures to Use
```python
# parrot_formdesigner/api/uploads.py:142
async def _stream_with_limit(part: Any, limit: int | None) -> AsyncIterator[bytes]:
    """Yield chunks from multipart part, raising 413 if limit exceeded."""
    ...

# parrot_formdesigner/api/uploads.py:172
def _build_auth_context(request: web.Request) -> AuthContext:
    """Extract authentication context from the request."""
    ...

# parrot_formdesigner/api/uploads.py:215
async def handle_rest_upload(request: web.Request) -> web.Response:
    """Existing REST upload handler — DO NOT modify its behavior."""
    ...

# parrot_formdesigner/services/blob_storage.py:125
class AbstractBlobStorage(ABC):
    async def put(self, stream: AsyncIterator[bytes], *,
                  metadata: BlobMetadata) -> str: ...
    async def delete(self, blob_ref: str) -> None: ...  # line 163

# parrot_formdesigner/core/resolution.py:170
def find_field_by_uid(
    form: FormSchema, field_uid: uuid.UUID
) -> tuple[FormField, FormSection] | None: ...

# parrot_formdesigner/api/tenant.py:166
def declared_tenant(request: web.Request) -> str: ...

# App-level references (aiohttp app dict keys):
# app["blob_storage"] — AbstractBlobStorage instance
# app["form_registry"] — FormRegistry instance
```

### Does NOT Exist
- ~~`parrot_formdesigner/api/file_upload.py`~~ — does not exist yet; this task creates it
- ~~`parrot_formdesigner/api/_upload_helpers.py`~~ — does not exist yet; this task creates it
- ~~`handle_file_upload`~~ — no such handler yet
- ~~`AbstractBlobStorage.put_bytes()`~~ — not a real method; must use `put()` with async iterator
- ~~`BlobMetadata.checksum`~~ — not an attribute of BlobMetadata
- ~~`_stream_with_limit` in `_upload_helpers.py`~~ — not extracted yet; currently in `uploads.py`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow handle_rest_upload pattern from api/uploads.py:215
# 1. Extract tenant, form_uid, field_uid from request.match_info
# 2. Resolve field via find_field_by_uid
# 3. Validate field_type is in UPLOAD_FIELD_TYPES
# 4. Parse multipart, iterate file parts
# 5. For each file: stream → blob storage → build FileEnvelope
# 6. Return JSON response
```

### Key Constraints
- **MIME detection**: Trust `Content-Type` from the multipart part first; optionally
  use `python-magic` if available for server-side verification
- **SHA-256 checksum**: Compute during streaming — accumulate a `hashlib.sha256()`
  as chunks flow through. Format: `"sha256:<hex>"`
- **data_url encoding**: Read blob bytes back, base64-encode, prepend
  `data:{content_type};base64,`. Only when `size ≤ max_inline_size_bytes`
- **Chunked upload**: Check for `X-Parrot-Upload-Offset` and `X-Parrot-Upload-Length`
  headers. If present: store chunk to blob storage with offset-tagged ref,
  when `offset + chunk_size == total_length`, reassemble and proceed normally
- **Single vs multi cardinality**: `is_single_cardinality(field_type)` determines
  whether to reject multiple file parts (400) or collect them as a list
- **Prior blob cleanup**: If `X-Parrot-Prior-Blob-Ref` header exists, call
  `blob_storage.delete(prior_ref)` after successful upload (fire-and-forget, log errors)
- **Response format**: Single FileEnvelope dict for single-cardinality fields,
  list of FileEnvelope dicts for multi-cardinality

### References in Codebase
- `api/uploads.py` — existing REST upload handler pattern
- `services/blob_storage.py` — blob storage API
- `services/thumbnail.py` — thumbnail generation (TASK-2444)

---

## Acceptance Criteria

- [ ] `_stream_with_limit` and `_build_auth_context` extracted to `api/_upload_helpers.py`
- [ ] `api/uploads.py` updated to import from `_upload_helpers` (no behavior change)
- [ ] `handle_file_upload` handler created and functional
- [ ] Returns FileEnvelope with all fields populated correctly
- [ ] Returns 415 for disallowed MIME types
- [ ] Returns 413 for oversized files
- [ ] Returns 400 for multi-file on single-cardinality field
- [ ] Returns 404 for non-upload field types
- [ ] data_url populated when size ≤ max_inline_size_bytes, None otherwise
- [ ] SHA-256 checksum always computed and included
- [ ] Thumbnail generation called for image content types
- [ ] X-Parrot-Prior-Blob-Ref triggers old blob deletion
- [ ] Basic chunked upload support works with offset/length headers
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_file_upload_handler.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_file_upload_handler.py
import pytest
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
from aiohttp.test_utils import make_mocked_request


# Tests should mock: blob_storage, form_registry, ThumbnailService
# Use aiohttp test utilities for request mocking

class TestFileUploadHandler:
    @pytest.mark.asyncio
    async def test_upload_single_file_returns_envelope(self):
        """Single file upload → FileEnvelope JSON response."""
        ...

    @pytest.mark.asyncio
    async def test_upload_multiple_files_multi_upload(self):
        """Multiple files to MULTI_UPLOAD → list of FileEnvelopes."""
        ...

    @pytest.mark.asyncio
    async def test_single_cardinality_rejects_multi(self):
        """FILE field + 2 file parts → 400."""
        ...

    @pytest.mark.asyncio
    async def test_mime_rejected(self):
        """allowed_mime_types=['image/png'] + upload image/jpeg → 415."""
        ...

    @pytest.mark.asyncio
    async def test_size_exceeded(self):
        """max_file_size_bytes=1000 + 2000-byte file → 413."""
        ...

    @pytest.mark.asyncio
    async def test_non_upload_field_type(self):
        """TEXT field_type → 404."""
        ...

    @pytest.mark.asyncio
    async def test_data_url_under_threshold(self):
        """File size < max_inline_size_bytes → data_url populated."""
        ...

    @pytest.mark.asyncio
    async def test_data_url_over_threshold(self):
        """File size > max_inline_size_bytes → data_url is None."""
        ...

    @pytest.mark.asyncio
    async def test_checksum_computed(self):
        """Checksum in response starts with 'sha256:'."""
        ...

    @pytest.mark.asyncio
    async def test_thumbnail_for_image(self):
        """Image upload → ThumbnailService.generate() called."""
        ...

    @pytest.mark.asyncio
    async def test_prior_blob_cleanup(self):
        """X-Parrot-Prior-Blob-Ref → old blob deleted."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2442, TASK-2443, TASK-2444 are completed
3. **Verify the Codebase Contract** — read `api/uploads.py` to confirm `_stream_with_limit` and `_build_auth_context` locations
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Extract helpers FIRST** — create `_upload_helpers.py`, update `uploads.py` imports
6. **Then implement** `handle_file_upload` in `file_upload.py`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2445-file-upload-handler.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
