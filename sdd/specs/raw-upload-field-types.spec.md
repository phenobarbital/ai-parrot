---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Raw Upload Field Types

**Feature ID**: FEAT-460
**Date**: 2026-08-25
**Author**: Jesus Lara / Claude
**Status**: approved
**Target version**: 0.10.0

---

## 1. Motivation & Business Requirements

### Problem Statement

The FormBuilder's upload/media field types (`FILE`, `IMAGE`, `IMAGE_DROPZONE`,
`MULTI_UPLOAD`) have **fragmented and lossy value shapes**. When a user uploads a
file, metadata essential for downstream processing — MIME type, file size, original
filename, extension — is either lost entirely or scattered across incompatible
structures:

| Field Type | Value Shape | What's Lost |
|---|---|---|
| `FILE` | `string` (URL or base64) | mime_type, size, filename, extension, blob_ref |
| `IMAGE` | `string` (URL or base64) | mime_type, size, filename, extension, blob_ref |
| `IMAGE_DROPZONE` | `{name, type, size, dataUrl}` | blob_ref (server storage) |
| `MULTI_UPLOAD` | `[{answer, blob_ref, display}]` | mime_type, size, filename |
| `REST` | `{answer, blob_ref}` + BlobMetadata backend | filename, extension in value |

Form designers cannot build forms that accept PDFs, DOCX, HTML, or Markdown as
first-class uploads because `FILE`/`IMAGE` have no structured metadata. Frontend
developers must use side-channel hacks (`{field_id}__mime` in `all_data`) to access
MIME type for validation. Backend and agent consumers cannot determine what type of
file was uploaded or its size without re-downloading the blob.

### Goals

1. Define a unified `FileEnvelope` Pydantic model as the canonical value shape for
   all upload field types.
2. All four upload types (`FILE`, `IMAGE`, `IMAGE_DROPZONE`, `MULTI_UPLOAD`) adopt
   the FileEnvelope shape.
3. Provide dual-read backward compatibility: validators accept both legacy string
   values and the new FileEnvelope without requiring data migration.
4. Create a dedicated file-upload endpoint separate from the existing REST upload
   handler.
5. Support multi-file uploads in a single request.
6. Include `blob_ref` (server storage) and `data_url` (inline base64) in every
   envelope, with a configurable size threshold for inline inclusion.
7. Provide optional server-side thumbnail generation for image uploads.
8. Enable uploading any MIME type by default, controlled by the existing
   `constraints.allowed_mime_types` field.
9. Provide basic chunked upload support for large files.

### Non-Goals (explicitly out of scope)

- **Modifying FieldType.REST**: The REST field pipeline (upload + external API
  callback) serves a different purpose and is untouched.
- **Creating new FieldType enum values**: No `DOCUMENT` or `MEDIA_UPLOAD` types —
  the existing types are enriched, not replaced. (Rejected in brainstorm Option C —
  see `sdd/proposals/raw-upload-field-types.brainstorm.md`.)
- **Full tus protocol compliance**: V1 includes basic chunked upload support but
  does not implement the full tus protocol (checksums, concatenation, expiration).
  Full tus compliance is a future enhancement.
- **Client-side thumbnail generation**: Thumbnails are generated server-side.
- **Metadata-only sidecar store**: Metadata lives IN the field value (FileEnvelope),
  not in an external table. (Rejected in brainstorm Option D.)

---

## 2. Architectural Design

### Overview

A single `FileEnvelope` Pydantic model becomes the canonical value shape for all
upload field types. The model is defined in `parrot_formdesigner/core/file_envelope.py`
and carries: `filename`, `content_type`, `size`, `blob_ref`, `data_url` (nullable
above a configurable threshold), `thumbnail_url` (optional, images only), and
`checksum` (optional, SHA-256).

A new dedicated upload endpoint
`POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload`
handles the binary pipeline for FILE, IMAGE, IMAGE_DROPZONE, and MULTI_UPLOAD
field types. It reuses the existing `AbstractBlobStorage` infrastructure
(S3, GCS, Local, Temp backends) and returns one or more FileEnvelopes.

The validator's `_coerce_value` method is extended to accept both legacy string
values and the new FileEnvelope dict for backward compatibility. Legacy submissions
continue to work without migration.

### Component Diagram

```
                        ┌──────────────────────────────────┐
                        │  POST .../file-upload            │
                        │  (api/file_upload.py)             │
                        └────────┬─────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
   │  MIME detect  │   │  Size check  │   │  Constraint      │
   │  + validate   │   │  (413 / ok)  │   │  enforcement     │
   └──────┬───────┘   └──────┬───────┘   └────────┬─────────┘
          │                  │                     │
          └──────────────────┼─────────────────────┘
                             ▼
                   ┌──────────────────┐
                   │ AbstractBlob     │
                   │ Storage.put()    │
                   │ → blob_ref       │
                   └────────┬─────────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
    ┌─────────────┐  ┌────────────┐  ┌──────────┐
    │ data_url    │  │ thumbnail  │  │ checksum │
    │ (if ≤       │  │ generation │  │ SHA-256  │
    │ threshold)  │  │ (images)   │  │          │
    └──────┬──────┘  └─────┬──────┘  └────┬─────┘
           │               │              │
           └───────────────┼──────────────┘
                           ▼
                  ┌──────────────────┐
                  │  FileEnvelope    │
                  │  JSON response   │
                  └──────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBlobStorage` (blob_storage.py) | uses | Reuse S3/GCS/Local/Temp backends via `put()` |
| `BlobMetadata` (blob_storage.py) | uses | Construct from upload request, passed to `put()` |
| `FieldConstraints` (constraints.py) | extends | Add `max_inline_size_bytes` field |
| `FormValidator._coerce_value` (validators.py) | modifies | Dual-read: accept string or FileEnvelope |
| `FormValidator._validate_by_type` (validators.py) | modifies | FileEnvelope-aware validation |
| `JsonSchemaRenderer` (jsonschema.py) | modifies | Update `_TYPE_MAP`, `_UNION_SHAPES`, `_STRUCTURAL_EXTRAS` |
| `Html5Renderer` (html5.py) | modifies | FILE/IMAGE render with envelope awareness |
| `PdfRenderer` (pdf.py) | modifies | Upload fields → envelope-aware fallback |
| `XFormsRenderer` (xforms.py) | modifies | Upload fields → envelope-aware |
| `AdaptiveCardRenderer` (adaptive_card.py) | modifies | Upload fields → envelope-aware |
| `TelegramRenderer` (telegram/renderer.py) | modifies | Upload fields → envelope-aware |
| `_BUILTIN_METADATA` (controls/builtin.py) | modifies | Update value_shape for upload types |
| `_FIELD_SCHEMA_SNIPPETS` (field_helpers.py) | modifies | Update snippets for upload types |
| `setup_form_api` (routes.py) | extends | Register `/file-upload` endpoint |
| `find_field_by_uid` (resolution.py) | uses | Resolve field from path params |
| `declared_tenant` (tenant.py) | uses | Extract tenant from request |

### Data Models

```python
# parrot_formdesigner/core/file_envelope.py (NEW)
from pydantic import BaseModel, ConfigDict, Field

class FileEnvelope(BaseModel):
    """Canonical value shape for all upload field types.

    Attributes:
        filename: Original filename with extension (e.g. "report.pdf").
        content_type: MIME type (e.g. "application/pdf").
        size: File size in bytes.
        blob_ref: Server-side storage reference (e.g. "s3://bucket/key").
            None when the file is inline-only (not persisted to blob storage).
        data_url: Inline base64 data URL (e.g. "data:image/png;base64,...").
            None when the file exceeds max_inline_size_bytes.
        thumbnail_url: URL to a server-generated thumbnail (images only).
            None for non-image files or when generation fails.
        checksum: SHA-256 integrity hash (e.g. "sha256:abcdef...").
            Always computed server-side from the received content.
    """

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(..., description="Original filename with extension")
    content_type: str = Field(..., description="MIME type of the file")
    size: int = Field(..., ge=0, description="File size in bytes")
    blob_ref: str | None = Field(default=None, description="Server storage reference")
    data_url: str | None = Field(default=None, description="Inline base64 data URL")
    thumbnail_url: str | None = Field(default=None, description="Thumbnail URL (images)")
    checksum: str | None = Field(default=None, description="SHA-256 hash")
```

```python
# Extension to FieldConstraints (constraints.py)
class FieldConstraints(BaseModel):
    # ... existing fields ...
    max_inline_size_bytes: int | None = Field(
        default=None, ge=0,
        description="Maximum file size for inline data_url inclusion. "
                    "Files above this threshold get blob_ref only. "
                    "Default (None) uses the system default of 10485760 (10MB)."
    )
```

### New Public Interfaces

```python
# parrot_formdesigner/api/file_upload.py (NEW)

async def handle_file_upload(request: web.Request) -> web.Response:
    """Handle POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload.

    Streams multipart upload(s) through the file upload pipeline:
    multipart → MIME/size check → blob storage → FileEnvelope(s) → JSON.

    Supports multiple 'file' parts in one request. Returns a single
    FileEnvelope for single-cardinality fields (FILE, IMAGE) or a list
    for multi-cardinality fields (IMAGE_DROPZONE multi, MULTI_UPLOAD).

    Accepts X-Parrot-Prior-Blob-Ref header for replacement uploads.
    """
    ...
```

```python
# Thumbnail service (parrot_formdesigner/services/thumbnail.py — NEW)

class ThumbnailService:
    """Server-side thumbnail generator for image uploads.

    Uses Pillow to resize images to 150×150 max, outputs WebP
    (quality 80). Persists thumbnails to blob storage and returns
    a relative URL.
    """

    def __init__(
        self,
        blob_storage: AbstractBlobStorage,
        max_width: int = 150,
        max_height: int = 150,
        quality: int = 80,
        output_format: str = "WEBP",
    ) -> None: ...

    async def generate(
        self,
        image_bytes: bytes,
        metadata: BlobMetadata,
    ) -> str | None:
        """Generate and persist a thumbnail. Returns thumbnail blob_ref or None."""
        ...
```

---

## 3. Module Breakdown

### Module 1: FileEnvelope Model
- **Path**: `parrot_formdesigner/core/file_envelope.py`
- **Responsibility**: Define the `FileEnvelope` Pydantic model. Define the
  `UPLOAD_FIELD_TYPES` frozenset constant (`{FILE, IMAGE, IMAGE_DROPZONE,
  MULTI_UPLOAD}`). Provide `is_single_cardinality(field_type)` helper.
- **Depends on**: `core/types.py` (FieldType)

### Module 2: FieldConstraints Extension
- **Path**: `parrot_formdesigner/core/constraints.py`
- **Responsibility**: Add `max_inline_size_bytes` field to `FieldConstraints`.
  System default constant `DEFAULT_MAX_INLINE_SIZE = 10_485_760` (10MB).
- **Depends on**: None (append-only change)

### Module 3: File Upload Handler
- **Path**: `parrot_formdesigner/api/file_upload.py`
- **Responsibility**: `handle_file_upload` request handler — multipart parsing,
  MIME detection, size enforcement, blob storage, data_url encoding, FileEnvelope
  construction. Supports multiple file parts per request. Includes basic chunked
  upload support: the endpoint accepts `X-Parrot-Upload-Offset` and
  `X-Parrot-Upload-Length` headers for clients that split large files into
  sequential chunks. Chunks are buffered in blob storage and assembled on the
  final chunk (when offset + chunk size == total length). Single-request multipart
  remains the primary path; chunked is the fallback for files over ~50MB.
- **Depends on**: Module 1, Module 2, `blob_storage.py`, `resolution.py`, `tenant.py`

### Module 4: Route Registration
- **Path**: `parrot_formdesigner/api/routes.py`
- **Responsibility**: Register `POST .../fields/{field_uid}/file-upload` route
  in `setup_form_api`. Import and wire `handle_file_upload`.
- **Depends on**: Module 3

### Module 5: Thumbnail Service
- **Path**: `parrot_formdesigner/services/thumbnail.py`
- **Responsibility**: Server-side thumbnail generation for image uploads using
  Pillow. Resize to 150×150 max, output WebP (quality 80). Persist to blob
  storage and return thumbnail blob_ref that the upload handler converts to a URL.
  Runs in `asyncio.to_thread()` to avoid blocking the event loop.
- **Depends on**: Module 1, `blob_storage.py`, `Pillow`

### Module 6: Validator Updates (Dual-Read Coercer)
- **Path**: `parrot_formdesigner/services/validators.py`
- **Responsibility**: Update `_coerce_value` for FILE, IMAGE, IMAGE_DROPZONE,
  MULTI_UPLOAD to accept both legacy shapes and FileEnvelope dicts. Update
  `_validate_by_type` for FileEnvelope-aware structural validation. Remove the
  MIME side-channel hack (`{field_id}__mime`) for FileEnvelope values (keep for
  legacy string values). Map legacy IMAGE_DROPZONE `{name,type,size,dataUrl}` and
  legacy MULTI_UPLOAD `{answer,blob_ref,display}` to FileEnvelope internally.
- **Depends on**: Module 1

### Module 7: JSON Schema Renderer Update
- **Path**: `parrot_formdesigner/renderers/jsonschema.py`
- **Responsibility**: Update `_TYPE_MAP` for FILE/IMAGE from `"string"` to
  `"object"`. Add FILE/IMAGE to `_UNION_SHAPES` (oneOf: string | FileEnvelope
  object). Add FileEnvelope properties to `_STRUCTURAL_EXTRAS`. Update
  `_field_to_property` for FileEnvelope-specific extensions.
- **Depends on**: Module 1

### Module 8: Other Renderers Update
- **Path**: `renderers/html5.py`, `renderers/pdf.py`, `renderers/xforms.py`,
  `renderers/adaptive_card.py`, `renderers/telegram/renderer.py`
- **Responsibility**: Each renderer's FILE/IMAGE/DROPZONE/MULTI_UPLOAD handling
  updated to be envelope-aware. For html5: `<input type="file">` unchanged but
  metadata attributes added. For pdf/adaptive_card: fallback text updated to show
  filename from envelope. For xforms: `upload` binding type preserved. For telegram:
  envelope-aware display.
- **Depends on**: Module 1

### Module 9: Controls & Helpers Update
- **Path**: `controls/builtin.py`, `tools/field_helpers.py`
- **Responsibility**: Update `_BUILTIN_METADATA` value entries and
  `_FIELD_SCHEMA_SNIPPETS` for FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD to
  reflect the FileEnvelope shape and `value_shape` output from
  `type_level_value_shape()`.
- **Depends on**: Module 1, Module 7

### Module 10: Test Suite
- **Path**: `tests/unit/test_file_envelope.py`, `tests/unit/test_file_upload_handler.py`,
  `tests/unit/test_validator_file_envelope.py`, `tests/integration/test_file_upload.py`
- **Responsibility**: Unit tests for FileEnvelope model, upload handler, dual-read
  coercer, thumbnail service. Integration test for end-to-end upload flow. Regression
  tests for legacy string value acceptance.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_file_envelope_required_fields` | 1 | filename, content_type, size are required |
| `test_file_envelope_optional_fields` | 1 | blob_ref, data_url, thumbnail_url, checksum default to None |
| `test_file_envelope_extra_forbid` | 1 | Extra fields rejected |
| `test_file_envelope_size_ge_zero` | 1 | Negative size rejected |
| `test_upload_field_types_constant` | 1 | `UPLOAD_FIELD_TYPES` contains exactly FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD |
| `test_is_single_cardinality` | 1 | FILE and IMAGE are single; DROPZONE and MULTI_UPLOAD are multi |
| `test_max_inline_size_bytes_field` | 2 | FieldConstraints accepts and validates new field |
| `test_upload_single_file` | 3 | Upload one file → single FileEnvelope response |
| `test_upload_multiple_files` | 3 | Upload N files → list of FileEnvelopes |
| `test_upload_single_field_rejects_multi` | 3 | FILE/IMAGE reject multiple file parts (400) |
| `test_upload_mime_rejected` | 3 | 415 when MIME not in allowed_mime_types |
| `test_upload_size_exceeded` | 3 | 413 when file exceeds max_file_size_bytes |
| `test_upload_data_url_under_threshold` | 3 | data_url populated when size ≤ max_inline_size_bytes |
| `test_upload_data_url_over_threshold` | 3 | data_url is None when size > max_inline_size_bytes |
| `test_upload_prior_blob_cleanup` | 3 | X-Parrot-Prior-Blob-Ref triggers old blob deletion |
| `test_upload_non_upload_field_type` | 3 | 404 for TEXT, SELECT, etc. |
| `test_thumbnail_generated_for_image` | 5 | Image upload produces thumbnail_url |
| `test_thumbnail_null_for_non_image` | 5 | PDF upload → thumbnail_url is None |
| `test_thumbnail_failure_non_fatal` | 5 | Corrupt image → warning, thumbnail_url None |
| `test_coerce_file_legacy_string` | 6 | Legacy string value accepted for FILE |
| `test_coerce_file_envelope_dict` | 6 | FileEnvelope dict accepted for FILE |
| `test_coerce_image_legacy_string` | 6 | Legacy string value accepted for IMAGE |
| `test_coerce_image_envelope_dict` | 6 | FileEnvelope dict accepted for IMAGE |
| `test_coerce_dropzone_legacy_shape` | 6 | `{name,type,size,dataUrl}` mapped to FileEnvelope |
| `test_coerce_dropzone_envelope` | 6 | FileEnvelope dict accepted directly |
| `test_coerce_multi_upload_legacy` | 6 | `[{answer,blob_ref,display}]` mapped to FileEnvelopes |
| `test_coerce_multi_upload_envelope` | 6 | `[FileEnvelope]` accepted directly |
| `test_validate_envelope_missing_required` | 6 | Missing filename/content_type/size → error |
| `test_jsonschema_file_union_shape` | 7 | FILE emits oneOf: [string, FileEnvelope] |
| `test_jsonschema_image_union_shape` | 7 | IMAGE emits oneOf: [string, FileEnvelope] |
| `test_jsonschema_dropzone_envelope` | 7 | IMAGE_DROPZONE emits FileEnvelope shape |
| `test_jsonschema_multi_upload_envelope` | 7 | MULTI_UPLOAD emits array of FileEnvelope |
| `test_builtin_value_shape_updated` | 9 | form-controls catalog shows FileEnvelope for upload types |
| `test_field_helpers_snippets_updated` | 9 | Snippets for FILE/IMAGE use envelope example |

### Integration Tests

| Test | Description |
|---|---|
| `test_file_upload_end_to_end` | Upload a file → verify FileEnvelope in response → submit form → verify stored |
| `test_file_upload_with_thumbnail` | Upload image → verify thumbnail_url is populated and retrievable |
| `test_legacy_submission_still_works` | Submit a form with legacy string FILE value → no errors |
| `test_multi_file_upload_end_to_end` | Upload 3 files to MULTI_UPLOAD → verify 3 FileEnvelopes |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_file_envelope():
    return {
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size": 183204,
        "blob_ref": "temp://form-uid/field-uid/blob-uuid",
        "data_url": None,  # over threshold
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
    """Legacy IMAGE_DROPZONE shape that must still be accepted."""
    return {"name": "photo.jpg", "type": "image/jpeg", "size": 45000, "dataUrl": "data:..."}

@pytest.fixture
def legacy_multi_upload_value():
    """Legacy MULTI_UPLOAD shape that must still be accepted."""
    return [{"answer": "result", "blob_ref": "s3://bucket/key", "display": "photo.jpg"}]
```

---

## 5. Acceptance Criteria

- [ ] `FileEnvelope` model defined with `filename`, `content_type`, `size` (required),
  `blob_ref`, `data_url`, `thumbnail_url`, `checksum` (optional)
- [ ] `FieldConstraints.max_inline_size_bytes` field added (default None → system
  default 5MB)
- [ ] `POST .../fields/{field_uid}/file-upload` endpoint registered and functional
- [ ] Upload endpoint returns 415 for disallowed MIME types
- [ ] Upload endpoint returns 413 for oversized files
- [ ] Upload endpoint returns 400 when single-cardinality field receives multiple files
- [ ] Upload endpoint returns 404 for non-upload field types
- [ ] `data_url` populated when file size ≤ `max_inline_size_bytes`, null otherwise
- [ ] `thumbnail_url` populated for image uploads, null for non-images
- [ ] `checksum` contains SHA-256 hash of uploaded content
- [ ] Multi-file upload: N file parts → N FileEnvelopes in response array
- [ ] Validator accepts legacy `string` value for FILE/IMAGE (dual-read)
- [ ] Validator accepts FileEnvelope dict for FILE/IMAGE
- [ ] Validator maps legacy `{name,type,size,dataUrl}` to FileEnvelope for IMAGE_DROPZONE
- [ ] Validator maps legacy `{answer,blob_ref,display}` to FileEnvelope for MULTI_UPLOAD
- [ ] JSON Schema for FILE/IMAGE emits `oneOf: [string, FileEnvelope object]`
- [ ] JSON Schema for IMAGE_DROPZONE/MULTI_UPLOAD emits FileEnvelope-based shape
- [ ] form-controls catalog `value_shape` updated for all four upload types
- [ ] `X-Parrot-Prior-Blob-Ref` header triggers old blob deletion
- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] No breaking changes to existing REST upload pipeline (FieldType.REST untouched)

---

## 6. Codebase Contract

### Verified Imports

```python
# These imports have been confirmed to work:
from parrot_formdesigner.core.types import FieldType                 # core/types.py:16
from parrot_formdesigner.core.schema import FormField                # core/schema.py:50
from parrot_formdesigner.core.constraints import FieldConstraints    # core/constraints.py
from parrot_formdesigner.services.blob_storage import (              # services/blob_storage.py
    AbstractBlobStorage,    # line 113
    BlobMetadata,           # line 55
    BlobRejectedError,      # line 41
    S3BlobStorage,          # line 341
    GCSBlobStorage,         # line 422
    LocalBlobStorage,       # line 476
    TempBlobStorage,        # line 527
)
from parrot_formdesigner.core.resolution import find_field_by_uid    # used in api/uploads.py:56
from parrot_formdesigner.api.tenant import declared_tenant           # used in api/uploads.py:67
from parrot_formdesigner.renderers.jsonschema import (
    _TYPE_MAP,              # line 26
    _UNION_SHAPES,          # line 92
    _STRUCTURAL_EXTRAS,     # line 156
    type_level_value_shape, # line 215
)
```

### Existing Class Signatures

```python
# parrot_formdesigner/core/types.py:16-71
class FieldType(str, Enum):
    FILE = "file"                    # line 29
    IMAGE = "image"                  # line 30
    IMAGE_DROPZONE = "image_dropzone"  # line 65
    MULTI_UPLOAD = "multi_upload"    # line 66
    REST = "rest"                    # line 51

# parrot_formdesigner/core/schema.py:50-108
class FormField(BaseModel):
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # line 91
    field_id: str                    # line 92
    field_type: FieldType            # line 93
    label: LocalizedString           # line 94
    required: bool = False           # line 97
    constraints: FieldConstraints | None = None  # line 100
    meta: dict[str, Any] | None = None           # line 108

# parrot_formdesigner/core/constraints.py:36-50
class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")        # line 36
    allowed_mime_types: list[str] | None = None       # line 47
    max_file_size_bytes: int | None = Field(           # line 48
        default=None, ge=0
    )
    # max_inline_size_bytes does NOT exist yet — Module 2 adds it

# parrot_formdesigner/services/blob_storage.py:55-88
class BlobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")  # line 78
    form_uid: uuid.UUID       # line 80
    form_id: str              # line 81
    field_uid: uuid.UUID      # line 82
    field_id: str             # line 83
    submission_id: str | None = None   # line 84
    tenant: str | None = None          # line 85
    content_type: str         # line 86
    size_bytes: int           # line 87

# parrot_formdesigner/services/blob_storage.py:113-182
class AbstractBlobStorage(ABC):
    async def put(self, stream: AsyncIterator[bytes], *,
                  metadata: BlobMetadata) -> str: ...     # line 125
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]: ...  # line 152
    async def delete(self, blob_ref: str) -> None: ...   # line 162
    async def pre_persist_hook(self, ctx: PrePersistContext) -> None: ...  # line 170
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FileEnvelope` | `FieldType` | `UPLOAD_FIELD_TYPES` frozenset | `core/types.py:29-66` |
| `handle_file_upload` | `AbstractBlobStorage.put()` | method call | `blob_storage.py:125` |
| `handle_file_upload` | `find_field_by_uid()` | function call | `core/resolution.py` (used in `api/uploads.py:56`) |
| `handle_file_upload` | `declared_tenant()` | function call | `api/tenant.py` (used in `api/uploads.py:67`) |
| `handle_file_upload` | `_stream_with_limit()` | function call | `api/uploads.py:142` |
| `handle_file_upload` | `_build_auth_context()` | function call | `api/uploads.py:172` |
| `setup_form_api` | `handle_file_upload` | route registration | `api/routes.py:375` (pattern from REST route) |
| `FormValidator._coerce_value` | `FileEnvelope` | dict validation | `services/validators.py` |
| `JsonSchemaRenderer` | `_TYPE_MAP`, `_UNION_SHAPES` | dict update | `renderers/jsonschema.py:26,92` |
| `_BUILTIN_METADATA` | `type_level_value_shape()` | function call | `controls/builtin.py` → `renderers/jsonschema.py:215` |

### Configuration References

- `PARROT_BLOB_BUCKET` — S3 bucket name (env var, used by S3BlobStorage)
- `PARROT_BLOB_PREFIX` — blob key prefix (env var, used by all backends)
- `PARROT_BLOB_PATH` — local filesystem base path (env var, LocalBlobStorage)
- `app["blob_storage"]` — AbstractBlobStorage instance on the aiohttp app
- `app["form_registry"]` — FormRegistry instance on the aiohttp app

### Does NOT Exist (Anti-Hallucination)

- ~~`FileEnvelope`~~ — does not exist yet; Module 1 creates it
- ~~`parrot_formdesigner/core/file_envelope.py`~~ — does not exist yet
- ~~`parrot_formdesigner/api/file_upload.py`~~ — does not exist yet
- ~~`parrot_formdesigner/services/thumbnail.py`~~ — does not exist yet
- ~~`handle_file_upload`~~ — no such handler function yet
- ~~`/file-upload` route~~ — not registered in routes.py yet
- ~~`FieldConstraints.max_inline_size_bytes`~~ — does not exist yet; Module 2 adds it
- ~~`FieldType.DOCUMENT`~~ — does not exist and is NOT being created
- ~~`FieldType.MEDIA_UPLOAD`~~ — does not exist and is NOT being created
- ~~`parrot_formdesigner/models/`~~ — this directory does not exist
- ~~`_coerce_value` branch for FILE/IMAGE~~ — FILE and IMAGE currently have NO
  dedicated coerce branch; they fall through as-is (string passthrough)
- ~~`_validate_file_field`~~ — does not exist; FILE/IMAGE validation is only the
  MIME side-channel check at validators.py:326-329

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Pydantic models for data structures**: FileEnvelope follows the same pattern as
  BlobMetadata (BaseModel with ConfigDict(extra="forbid"), typed fields).
- **aiohttp handler pattern**: `handle_file_upload` follows the same structure as
  `handle_rest_upload` in `api/uploads.py` — extract form_uid/field_uid, resolve
  field, parse multipart, enforce constraints, build response.
- **Streaming with limit**: Use `_stream_with_limit` from `api/uploads.py:142` for
  size enforcement during upload streaming.
- **Auth context pattern**: Use `_build_auth_context` from `api/uploads.py:172` for
  request authentication.
- **Route registration**: Follow the pattern at `routes.py:375` — `app.router.add_post`
  with `_wrap_auth` decorator.
- **Dual-shape rendering via `_UNION_SHAPES`**: Follow the TREE_SELECT pattern
  (jsonschema.py:93-96) for emitting `oneOf: [string, object]`.
- **Validator coercion pattern**: Follow existing `_coerce_value` branches — type
  check, coerce, return. The IMAGE_DROPZONE branch (validators.py:558-561) and
  MULTI_UPLOAD branch (validators.py:563-566) are the templates for legacy mapping.

### Known Risks / Gotchas

- **Breaking change for typeof checks**: Frontend code that checks
  `typeof value === 'string'` for FILE/IMAGE will break when the value is a
  FileEnvelope object. Mitigated by the `oneOf` schema advertising both shapes.
- **data_url storage cost**: Files under the threshold are stored TWICE — once as
  blob_ref in storage and once as base64 in the submission value. This is
  intentional (dual storage for immediate frontend access without a GET).
- **Thumbnail generation blocking**: Pillow operations are CPU-bound. Must run in
  `asyncio.to_thread()` to avoid blocking the event loop.
- **IMAGE_DROPZONE legacy mapping is lossy**: The legacy `{name,type,size,dataUrl}`
  shape has no `blob_ref` — the mapped FileEnvelope will have `blob_ref=None`. This
  is correct: legacy values were never server-persisted.
- **MULTI_UPLOAD legacy mapping is lossy**: The legacy `{answer,blob_ref,display}`
  shape has no `size` or `content_type`. The mapped FileEnvelope will have
  `size=0` and `content_type="application/octet-stream"` as fallbacks.
- **`_stream_with_limit` and `_build_auth_context`** are private functions in
  `api/uploads.py`. To reuse them in `api/file_upload.py`, either:
  (a) import them directly (they are module-level, not class methods), or
  (b) extract them to a shared `api/_upload_helpers.py` module. Option (b) is
  preferred for cleanliness.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `Pillow` | `>=10.0` | Thumbnail generation (resize, format conversion). Already in parrot-formdesigner deps. |
| `python-magic` | `>=0.4.27` | Optional: server-side MIME detection from file content (not header). Fallback: trust Content-Type header. |

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: The FileEnvelope model (Module 1) is foundational — every other
  module imports it. The validator, renderers, and controls all touch shared dicts
  (`_TYPE_MAP`, `_UNION_SHAPES`, `_BUILTIN_METADATA`). Sequential execution in
  one worktree avoids merge conflicts and keeps the implementation coherent.
- **Cross-feature dependencies**: None blocking. The merge from origin/dev brought
  in the formschema persistence feature (TASK-2417..2431) which touches
  `api/routes.py` and `api/handlers.py` — both files this feature also modifies.
  The changes are append-only (new route, new handler) so no conflict expected.

---

## 8. Open Questions

- [x] What is the default value for `max_inline_size_bytes`? **Resolved: 10485760 (10 MB).** — *Owner: Jesus*
- [x] Should `checksum` be computed server-side (always) or client-side (optional, verified server-side)? **Resolved: Always computed server-side (SHA-256). Client never sends a checksum.** — *Owner: Jesus*
- [x] Thumbnail dimensions and format — 200×200 JPEG? Configurable? **Resolved: 150×150 max, WebP output, quality 80. Not configurable in V1.** — *Owner: Jesus*
- [x] Should the `/file-upload` endpoint support chunked/resumable uploads (tus protocol), or is single-request multipart sufficient for V1? **Resolved: Basic chunked upload support in V1 via `X-Parrot-Upload-Offset` / `X-Parrot-Upload-Length` headers. Full tus protocol compliance is a non-goal.** — *Owner: Jesus*
- [x] How should the frontend migration work? Feature flag? Gradual rollout per field type? **Resolved: No feature flag. Backend always returns FileEnvelope; frontend adopts when ready (dual-read coercer guarantees backward compatibility).** — *Owner: Frontend team*
- [x] Should `data_url` be stored in the submission DB or reconstructed on-demand from blob_ref? Storing it doubles storage for files under the threshold. **Resolved: Store `data_url` in the submission DB. Simplicity and read-speed outweigh the storage cost for files ≤ 10 MB.** — *Owner: Jesus*

---

## 9. Follow-up Work

- **TASK-2469 — Thumbnail Serving Route.** Raised by the adversarial code
  review during implementation: `FileEnvelope.thumbnail_url` is documented
  (and fixtured in §4's `sample_image_envelope`) as a real HTTP path, but
  the shipped V1 populates it with the raw blob storage reference instead
  (no thumbnail-serving route exists in `api/routes.py`). Tracked as a
  dedicated follow-up task under this same spec rather than blocking the
  rest of FEAT-460 — `thumbnail_url` populated/null correctness (the
  literal §5 acceptance criterion) is unaffected; only its *fetchability*
  as a URL is deferred. See `sdd/tasks/completed/TASK-2469-thumbnail-serving-route.md`
  once done (or `sdd/tasks/active/` if still pending).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-25 | Jesus Lara / Claude | Initial draft from brainstorm Option B |
| 0.2 | 2026-08-25 | Jesus Lara / Claude | Resolved all 6 open questions; updated defaults (10 MB inline threshold, 150×150 WebP thumbnails, server-side SHA-256 checksum, basic chunked upload support, no feature flag, data_url stored in DB) |
| 0.3 | 2026-08-25 | sdd-worker (Claude Sonnet 5) | Added §9 Follow-up Work — TASK-2469 (thumbnail serving route), raised by the FEAT-460 adversarial code review |
