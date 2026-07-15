---
type: Wiki Entity
title: AbstractBlobStorage
id: class:parrot_formdesigner.services.blob_storage.AbstractBlobStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract async blob storage.
---

# AbstractBlobStorage

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class AbstractBlobStorage(ABC)
```

Abstract async blob storage.

Concrete implementations: ``S3BlobStorage``, ``GCSBlobStorage``,
``LocalBlobStorage``, ``TempBlobStorage``, and any user-supplied backend
inheriting from this class.

All methods are async. The ``pre_persist_hook`` is called by ``put``
before writing; subclasses may raise ``BlobRejectedError`` to abort.

## Methods

- `async def put(self, stream: AsyncIterator[bytes], *, metadata: BlobMetadata) -> str` — Persist a blob and return a stable blob reference.
- `async def get(self, blob_ref: str) -> AsyncIterator[bytes]` — Stream a blob by reference.
- `async def delete(self, blob_ref: str) -> None` — Delete a blob by reference. Idempotent — no error if missing.
- `async def pre_persist_hook(self, ctx: PrePersistContext) -> None` — Pre-write hook for AV/content-scanning. V1 default: no-op.
