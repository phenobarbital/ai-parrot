# TASK-2444: Thumbnail Service

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2442
**Assigned-to**: unassigned

---

## Context

The thumbnail service generates server-side thumbnails for image uploads.
When a user uploads an image through the file-upload endpoint, this service
creates a 150×150 WebP thumbnail, stores it via blob storage, and returns
the blob_ref for inclusion in the FileEnvelope's `thumbnail_url` field.
Implements **Module 5** from the spec.

---

## Scope

- Create `parrot_formdesigner/services/thumbnail.py` with `ThumbnailService` class:
  - Constructor takes `AbstractBlobStorage`, optional `max_width` (150),
    `max_height` (150), `quality` (80), `output_format` ("WEBP").
  - `async def generate(image_bytes, metadata) -> str | None` — resize, convert,
    persist to blob storage, return thumbnail blob_ref. Returns `None` on failure
    (corrupt image, unsupported format) with a warning log.
  - CPU-bound Pillow work runs in `asyncio.to_thread()`.
- Write unit tests with mocked blob storage.

**NOT in scope**: Wiring into the upload handler (TASK-2445 does that),
route registration (TASK-2446).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/thumbnail.py` | CREATE | ThumbnailService class |
| `packages/parrot-formdesigner/tests/unit/test_thumbnail_service.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.blob_storage import (
    AbstractBlobStorage,    # line 113
    BlobMetadata,           # line 55
)
```

### Existing Signatures to Use
```python
# parrot_formdesigner/services/blob_storage.py:113-125
class AbstractBlobStorage(ABC):
    async def put(self, stream: AsyncIterator[bytes], *,
                  metadata: BlobMetadata) -> str:  # line 125
        """Store bytes from stream, return blob_ref."""
        ...

# parrot_formdesigner/services/blob_storage.py:55-87
class BlobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")  # line 78
    form_uid: uuid.UUID       # line 80
    form_id: str              # line 81
    field_uid: uuid.UUID      # line 82
    field_id: str             # line 83
    submission_id: str | None = None  # line 84
    tenant: str | None = None         # line 85
    content_type: str         # line 86
    size_bytes: int           # line 87
```

### Does NOT Exist
- ~~`parrot_formdesigner/services/thumbnail.py`~~ — does not exist yet; this task creates it
- ~~`ThumbnailService`~~ — does not exist anywhere
- ~~`AbstractBlobStorage.put_bytes()`~~ — no such convenience method; use `put()` with an async iterator
- ~~`BlobMetadata.original_blob_ref`~~ — not a real attribute

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import logging
from io import BytesIO
from collections.abc import AsyncIterator
from PIL import Image
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage, BlobMetadata

logger = logging.getLogger(__name__)


class ThumbnailService:
    """Server-side thumbnail generator for image uploads."""

    def __init__(
        self,
        blob_storage: AbstractBlobStorage,
        max_width: int = 150,
        max_height: int = 150,
        quality: int = 80,
        output_format: str = "WEBP",
    ) -> None:
        self._storage = blob_storage
        self._max_width = max_width
        self._max_height = max_height
        self._quality = quality
        self._format = output_format

    async def generate(
        self, image_bytes: bytes, metadata: BlobMetadata,
    ) -> str | None:
        """Generate and persist a thumbnail. Returns thumbnail blob_ref or None."""
        try:
            thumb_bytes = await asyncio.to_thread(
                self._resize, image_bytes
            )
        except Exception:
            logger.warning("Thumbnail generation failed for %s", metadata.field_id, exc_info=True)
            return None

        # Build thumbnail-specific metadata
        thumb_meta = BlobMetadata(
            form_uid=metadata.form_uid,
            form_id=metadata.form_id,
            field_uid=metadata.field_uid,
            field_id=f"{metadata.field_id}__thumb",
            content_type=f"image/{self._format.lower()}",
            size_bytes=len(thumb_bytes),
            tenant=metadata.tenant,
        )

        async def _stream() -> AsyncIterator[bytes]:
            yield thumb_bytes

        return await self._storage.put(_stream(), metadata=thumb_meta)

    def _resize(self, image_bytes: bytes) -> bytes:
        """Synchronous thumbnail generation (runs in thread)."""
        img = Image.open(BytesIO(image_bytes))
        img.thumbnail((self._max_width, self._max_height))
        buf = BytesIO()
        img.save(buf, format=self._format, quality=self._quality)
        return buf.getvalue()
```

### Key Constraints
- Pillow's `Image.open` / `thumbnail` / `save` are CPU-bound — must run in `asyncio.to_thread()`
- Failure (corrupt image, unsupported format like SVG) must NOT crash the upload — return `None` with warning
- `AbstractBlobStorage.put()` expects `AsyncIterator[bytes]`, not raw bytes — wrap in an async generator
- Thumbnail metadata uses `{field_id}__thumb` suffix to distinguish from the original blob
- Use `image/webp` as `content_type` for thumbnail metadata

---

## Acceptance Criteria

- [ ] `ThumbnailService` class created with `generate()` method
- [ ] Thumbnails are 150×150 max, WebP, quality 80
- [ ] Pillow operations run in `asyncio.to_thread()`
- [ ] Corrupt/unsupported images return `None` (non-fatal)
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_thumbnail_service.py -v`
- [ ] Import works: `from parrot_formdesigner.services.thumbnail import ThumbnailService`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_thumbnail_service.py
import uuid
import pytest
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from PIL import Image
from parrot_formdesigner.services.thumbnail import ThumbnailService
from parrot_formdesigner.services.blob_storage import BlobMetadata


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.put = AsyncMock(return_value="temp://thumb-ref")
    return storage


@pytest.fixture
def sample_metadata():
    return BlobMetadata(
        form_uid=uuid.uuid4(), form_id="test-form",
        field_uid=uuid.uuid4(), field_id="photo",
        content_type="image/jpeg", size_bytes=10000,
    )


@pytest.fixture
def valid_image_bytes():
    img = Image.new("RGB", (800, 600), color="red")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestThumbnailService:
    @pytest.mark.asyncio
    async def test_generate_returns_blob_ref(self, mock_storage, sample_metadata, valid_image_bytes):
        svc = ThumbnailService(mock_storage)
        ref = await svc.generate(valid_image_bytes, sample_metadata)
        assert ref == "temp://thumb-ref"
        mock_storage.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_thumbnail_dimensions(self, mock_storage, sample_metadata, valid_image_bytes):
        svc = ThumbnailService(mock_storage, max_width=150, max_height=150)
        await svc.generate(valid_image_bytes, sample_metadata)
        # Verify the stored bytes are a valid thumbnail
        call_args = mock_storage.put.call_args
        stream = call_args[0][0]  # first positional arg = async iterator
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        thumb_bytes = b"".join(chunks)
        img = Image.open(BytesIO(thumb_bytes))
        assert img.width <= 150
        assert img.height <= 150

    @pytest.mark.asyncio
    async def test_corrupt_image_returns_none(self, mock_storage, sample_metadata):
        svc = ThumbnailService(mock_storage)
        result = await svc.generate(b"not an image", sample_metadata)
        assert result is None
        mock_storage.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_metadata_uses_thumb_suffix(self, mock_storage, sample_metadata, valid_image_bytes):
        svc = ThumbnailService(mock_storage)
        await svc.generate(valid_image_bytes, sample_metadata)
        call_kwargs = mock_storage.put.call_args[1]
        meta = call_kwargs["metadata"]
        assert meta.field_id == f"{sample_metadata.field_id}__thumb"
        assert meta.content_type == "image/webp"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2442 is completed
3. **Verify the Codebase Contract** — confirm `AbstractBlobStorage.put()` signature and `BlobMetadata` fields
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the ThumbnailService
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2444-thumbnail-service.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-25
**Notes**: Implemented `ThumbnailService` exactly per the contract pattern —
constructor takes `AbstractBlobStorage` + max_width/max_height/quality/
output_format, `generate()` resizes via Pillow inside `asyncio.to_thread`,
persists via `AbstractBlobStorage.put()` with `{field_id}__thumb` metadata,
and returns `None` (with a warning log) on failure. Added
`test_thumbnail_service.py` per the task's Test Specification verbatim.
All 4 tests pass.

**Deviations from spec**: none
