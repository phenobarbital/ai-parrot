# TASK-2451: Integration & Regression Tests

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2442, TASK-2443, TASK-2444, TASK-2445, TASK-2446, TASK-2447, TASK-2448, TASK-2449, TASK-2450
**Assigned-to**: unassigned

---

## Context

This is the final task for FEAT-460. It adds end-to-end integration tests that
exercise the complete file upload pipeline — from HTTP request through blob
storage to FileEnvelope response — and regression tests that verify legacy
form submissions still work without changes. Implements **Module 10** from the spec.

---

## Scope

- Create integration tests that:
  - Upload a file through the `/file-upload` endpoint → verify FileEnvelope response
  - Upload an image → verify `thumbnail_url` is populated and retrievable
  - Submit a form with a legacy string FILE value → verify no errors (regression)
  - Upload multiple files to MULTI_UPLOAD → verify list of FileEnvelopes
- Create test fixtures:
  - `sample_file_envelope` — PDF FileEnvelope dict
  - `sample_image_envelope` — JPEG FileEnvelope dict with thumbnail
  - `legacy_dropzone_value` — legacy `{name,type,size,dataUrl}` shape
  - `legacy_multi_upload_value` — legacy `[{answer,blob_ref,display}]` shape
- Verify chunked upload flow works end-to-end.

**NOT in scope**: Unit tests for individual modules (those are in TASK-2442..2450).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/test_file_upload.py` | CREATE | End-to-end upload tests |
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | Add shared fixtures (if not already present) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.file_envelope import (
    FileEnvelope, UPLOAD_FIELD_TYPES, is_single_cardinality,
)  # created by TASK-2442
from parrot_formdesigner.core.types import FieldType  # core/types.py:16
from parrot_formdesigner.core.constraints import (
    FieldConstraints, DEFAULT_MAX_INLINE_SIZE,
)  # extended by TASK-2443
from parrot_formdesigner.services.blob_storage import (
    TempBlobStorage,  # line 527 — in-memory blob storage for tests
)
```

### Existing Signatures to Use
```python
# aiohttp test utilities:
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
# or use pytest-aiohttp fixtures: aiohttp_client

# parrot_formdesigner/api/routes.py:165
def setup_form_api(app: web.Application, *, prefix: str = "/api/v1") -> None:
    ...

# TempBlobStorage — in-memory backend, no external deps
# parrot_formdesigner/services/blob_storage.py:527
class TempBlobStorage(AbstractBlobStorage):
    """In-memory blob storage for testing."""
    ...
```

### Does NOT Exist
- ~~`parrot_formdesigner/tests/integration/test_file_upload.py`~~ — does not exist yet
- ~~`TestClient` from parrot_formdesigner~~ — use aiohttp test utilities
- ~~`MockBlobStorage`~~ — use `TempBlobStorage` from blob_storage.py

---

## Implementation Notes

### Test App Setup Pattern
```python
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.services.blob_storage import TempBlobStorage


@pytest.fixture
def app():
    app = web.Application()
    app["blob_storage"] = TempBlobStorage()
    # Set up a minimal form registry with test forms
    # that have FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD fields
    setup_form_api(app)
    return app
```

### Key Constraints
- Use `TempBlobStorage` for tests — no external storage dependency
- Use `aiohttp_client` pytest fixture or `AioHTTPTestCase` for HTTP testing
- Test multipart upload construction with `aiohttp.FormData`
- Verify response JSON against `FileEnvelope.model_validate()` for schema correctness
- Legacy regression tests must use the EXISTING submission endpoints (not the new
  `/file-upload` endpoint) to verify backward compatibility
- Chunked upload test: send 2 requests with different offsets, verify final assembly

### Test Fixtures (from spec §4)
```python
@pytest.fixture
def sample_file_envelope():
    return {
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size": 183204,
        "blob_ref": "temp://form-uid/field-uid/blob-uuid",
        "data_url": None,
        "thumbnail_url": None,
        "checksum": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }

@pytest.fixture
def sample_image_envelope():
    return {
        "filename": "photo.jpg",
        "content_type": "image/jpeg",
        "size": 45000,
        "blob_ref": "temp://form-uid/field-uid/blob-uuid",
        "data_url": "data:image/jpeg;base64,/9j/4AAQ...",
        "thumbnail_url": "/api/v1/test-tenant/forms/form-uid/fields/field-uid/thumbnail/thumb-uuid",
        "checksum": "sha256:abc123...",
    }

@pytest.fixture
def legacy_dropzone_value():
    return {"name": "photo.jpg", "type": "image/jpeg", "size": 45000, "dataUrl": "data:..."}

@pytest.fixture
def legacy_multi_upload_value():
    return [{"answer": "result", "blob_ref": "s3://bucket/key", "display": "photo.jpg"}]
```

---

## Acceptance Criteria

- [ ] End-to-end upload test: file → FileEnvelope response with all fields
- [ ] Image upload test: thumbnail_url populated
- [ ] Legacy string FILE submission: no errors (regression)
- [ ] Multi-file upload: N files → N FileEnvelopes
- [ ] Chunked upload test: 2 chunks → assembled file → FileEnvelope
- [ ] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/test_file_upload.py -v`
- [ ] FileEnvelope response validates against `FileEnvelope.model_validate()`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/integration/test_file_upload.py

class TestFileUploadEndToEnd:
    @pytest.mark.asyncio
    async def test_file_upload_returns_envelope(self, aiohttp_client):
        """Upload a PDF → FileEnvelope with filename, content_type, size, blob_ref, checksum."""
        ...

    @pytest.mark.asyncio
    async def test_image_upload_with_thumbnail(self, aiohttp_client):
        """Upload JPEG → FileEnvelope with thumbnail_url populated."""
        ...

    @pytest.mark.asyncio
    async def test_multi_file_upload(self, aiohttp_client):
        """Upload 3 files to MULTI_UPLOAD → list of 3 FileEnvelopes."""
        ...

    @pytest.mark.asyncio
    async def test_chunked_upload(self, aiohttp_client):
        """Upload in 2 chunks → assembled file → FileEnvelope."""
        ...


class TestLegacyRegression:
    @pytest.mark.asyncio
    async def test_legacy_string_file_accepted(self, aiohttp_client):
        """Submit form with legacy string FILE value → no validation errors."""
        ...

    @pytest.mark.asyncio
    async def test_legacy_dropzone_shape_accepted(self, aiohttp_client):
        """Submit form with legacy {name,type,size,dataUrl} → accepted."""
        ...

    @pytest.mark.asyncio
    async def test_legacy_multi_upload_shape_accepted(self, aiohttp_client):
        """Submit form with legacy [{answer,blob_ref,display}] → accepted."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — ALL prior tasks (TASK-2442..2450) must be completed
3. **Verify the Codebase Contract** — confirm all new modules are in place
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Set up test app** with TempBlobStorage and test forms
6. **Implement** all integration and regression tests
7. **Run the full test suite** to verify everything passes together
8. **Move this file** to `sdd/tasks/completed/TASK-2451-integration-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
