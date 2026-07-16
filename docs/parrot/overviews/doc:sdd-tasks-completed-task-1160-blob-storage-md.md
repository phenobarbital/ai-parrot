---
type: Wiki Overview
title: 'TASK-1160: `AbstractBlobStorage` + `S3BlobStorage` + pre-persist hook stub'
id: doc:sdd-tasks-completed-task-1160-blob-storage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1 foundation service. `FieldType.REST` persists binary uploads
---

# TASK-1160: `AbstractBlobStorage` + `S3BlobStorage` + pre-persist hook stub

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 1)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Phase 1 foundation service. `FieldType.REST` persists binary uploads
alongside form submissions via a pluggable async blob-storage layer
(default S3 via `aioboto3`). The `pre_persist_hook` is a stub interface
in V1 — the full AV/content-scanning pipeline is V2. See spec §2
*Architectural Design* and §8 Q8 (resolved).

---

## Scope

- Implement `parrot_formdesigner/services/blob_storage.py` with:
  - `BlobMetadata` and `PrePersistContext` Pydantic v2 models
    (`ConfigDict(extra="forbid")`).
  - `BlobRejectedError` exception (raised by hooks to abort `put`).
  - `AbstractBlobStorage` ABC: async `put`/`get`/`delete` +
    `pre_persist_hook` default no-op coroutine.
  - `S3BlobStorage(AbstractBlobStorage)` concrete impl using
    `aioboto3.Session().client("s3")`. Bucket/prefix/endpoint
    configurable via constructor with env-var fallback
    (`PARROT_BLOB_BUCKET`, `PARROT_BLOB_PREFIX`,
    `PARROT_BLOB_ENDPOINT_URL`).
- Stream-friendly `put`: accepts `AsyncIterator[bytes]`. Does NOT buffer
  the whole blob in memory.
- `S3BlobStorage.delete` is idempotent (absent key does not raise).
- Unit tests under `tests/unit/services/test_blob_storage.py` mocking
  `aioboto3` (no live S3 calls).

**NOT in scope**: AV scanning logic, retention policies, GCS/local-FS
backends, integration with the upload route (TASK-1170).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py` | CREATE | Module |
| `packages/parrot-formdesigner/tests/unit/services/test_blob_storage.py` | CREATE | Unit tests (mock aioboto3) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Standard
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
import logging
import os

# Third-party
from pydantic import BaseModel, ConfigDict
# aioboto3 >= 12.0 — added by TASK-1169 in pyproject.toml; this task
# may use a deferred import inside S3BlobStorage if pyproject not yet
# updated locally.
```

### Existing Signatures to Use

None — this module has no existing-codebase callers in V1.
`AuthContext` and other services are NOT needed here (upload-time
auth is the handler's concern, not the storage's).

### Does NOT Exist

- ~~`parrot_formdesigner.services.blob_storage`~~ — this module is new.
- ~~`AbstractBlobStorage` / `S3BlobStorage` / `BlobMetadata` /
  `PrePersistContext` / `BlobRejectedError`~~ — all new.
- ~~`aioboto3`~~ — NOT in `pyproject.toml` yet (TASK-1169 adds it).
- ~~`boto3` / `botocore` (sync clients)~~ — forbidden, async only.

---

## Implementation Notes

### Model shapes (from spec §2)

```python
class BlobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    form_id: str
    field_id: str
    submission_id: str | None = None
    tenant: str | None = None
    content_type: str
    size_bytes: int

class PrePersistContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metadata: BlobMetadata
    content_preview: bytes | None = None
```

### Key constraints

- Async everywhere — `put` accepts `AsyncIterator[bytes]` and streams
  to `aioboto3` via multipart upload (`MultipartUpload` or
  `upload_fileobj` with an async-friendly wrapper).
- Track bytes read during streaming so callers can enforce
  `max_file_size_bytes` upstream (no need to enforce inside
  `S3BlobStorage` — that's the handler's job).
- `pre_persist_hook` default impl is `async def pre_persist_hook(self,
  ctx: PrePersistContext) -> None: return None`. A subclass may raise
  `BlobRejectedError` to abort.
- `blob_ref` format: `s3://<bucket>/<prefix>/<form_id>/<field_id>/<uuid>`.
- Use `self.logger = logging.getLogger(__name__)` — never `print`.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.services.blob_storage import (AbstractBlobStorage, S3BlobStorage, BlobMetadata, PrePersistContext, BlobRejectedError)` succeeds.
- [ ] `AbstractBlobStorage` is an ABC; instantiating directly raises `TypeError`.
- [ ] `S3BlobStorage.put` mocked-aioboto3 test asserts put-object payload + key.
- [ ] `S3BlobStorage.delete("s3://bucket/nonexistent-key")` does not raise.
- [ ] `S3BlobStorage.pre_persist_hook` default returns `None` (no-op).
- [ ] A subclass raising `BlobRejectedError` from `pre_persist_hook` aborts `put` without writing.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/services/test_blob_storage.py -v` passes.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py` clean.

---

## Test Specification

```python
# tests/unit/services/test_blob_storage.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_formdesigner.services.blob_storage import (
    AbstractBlobStorage, S3BlobStorage, BlobMetadata,
    PrePersistContext, BlobRejectedError,
)

class TestAbstractBlobStorage:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AbstractBlobStorage()

class TestS3BlobStorage:
    @pytest.fixture
    def storage(self):
        return S3BlobStorage(bucket="test-bucket", prefix="forms/")

    async def test_put_returns_s3_ref(self, storage):
        async def chunks():
            yield b"hello"
        with patch("aioboto3.Session") as session:
            # mock S3 client put_object
            ref = await storage.put(chunks(), metadata=BlobMetadata(
                form_id="f1", field_id="photo",
                content_type="image/jpeg", size_bytes=5))
        assert ref.startswith("s3://test-bucket/forms/")

    async def test_delete_absent_key_no_raise(self, storage):
        with patch("aioboto3.Session"):
            await storage.delete("s3://test-bucket/forms/missing")

    async def test_pre_persist_hook_noop(self, storage):
        ctx = PrePersistContext(metadata=BlobMetadata(
            form_id="f1", field_id="x",
            content_type="text/plain", size_bytes=0))
        assert await storage.pre_persist_hook(ctx) is None

    async def test_pre_persist_hook_reject_aborts_put(self):
        class Strict(S3BlobStorage):
            async def pre_persist_hook(self, ctx):
                raise BlobRejectedError("reject")
        storage = Strict(bucket="b", prefix="p/")
        async def chunks():
            yield b"x"
        with patch("aioboto3.Session"):
            with pytest.raises(BlobRejectedError):
                await storage.put(chunks(), metadata=BlobMetadata(
                    form_id="f", field_id="x",
                    content_type="text/plain", size_bytes=1))
```

---

## Agent Instructions

Standard SDD task flow. Before coding:
- `grep -r "aioboto3" packages/parrot-formdesigner/pyproject.toml` —
  if missing, install locally via `uv pip install 'aioboto3>=12.0'`
  for tests; the pyproject pinning lands via TASK-1169.

---

## Completion Note

*(Agent fills this in when done)*
