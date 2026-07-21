---
type: Wiki Summary
title: parrot_formdesigner.services.blob_storage
id: mod:parrot_formdesigner.services.blob_storage
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async blob storage abstraction for FieldType.REST uploads.
relates_to:
- concept: class:parrot_formdesigner.services.blob_storage.AbstractBlobStorage
  rel: defines
- concept: class:parrot_formdesigner.services.blob_storage.BlobMetadata
  rel: defines
- concept: class:parrot_formdesigner.services.blob_storage.BlobRejectedError
  rel: defines
- concept: class:parrot_formdesigner.services.blob_storage.GCSBlobStorage
  rel: defines
- concept: class:parrot_formdesigner.services.blob_storage.LocalBlobStorage
  rel: defines
- concept: class:parrot_formdesigner.services.blob_storage.PrePersistContext
  rel: defines
- concept: class:parrot_formdesigner.services.blob_storage.S3BlobStorage
  rel: defines
- concept: class:parrot_formdesigner.services.blob_storage.TempBlobStorage
  rel: defines
---

# `parrot_formdesigner.services.blob_storage`

Async blob storage abstraction for FieldType.REST uploads.

Provides ``AbstractBlobStorage`` (ABC) plus concrete backends — ``S3BlobStorage``,
``GCSBlobStorage``, ``LocalBlobStorage``, ``TempBlobStorage`` — each implemented
as a thin adapter over the matching ``navigator.utils.file`` ``FileManager``.

Credential resolution and provider-specific I/O live in the ``FileManager``
implementations; this module only handles:

* ``BlobMetadata`` → object key construction (``{prefix}{form_id}/{field_id}/{uuid}``).
* ``blob_ref`` round-tripping (scheme + key).
* The ``pre_persist_hook`` extension point.

The ``put`` contract collects the inbound async byte stream into memory before
writing — sufficient for V1 form uploads, which are size-bounded by the
multipart parser upstream. Streaming/multipart uploads are delegated to the
FileManager when applicable.

## Classes

- **`BlobRejectedError(Exception)`** — Raised by ``AbstractBlobStorage.pre_persist_hook`` to abort a ``put``.
- **`BlobMetadata(BaseModel)`** — Metadata associated with a persisted blob.
- **`PrePersistContext(BaseModel)`** — Context passed to ``AbstractBlobStorage.pre_persist_hook`` before writing.
- **`AbstractBlobStorage(ABC)`** — Abstract async blob storage.
- **`S3BlobStorage(_ManagerBackedBlobStorage)`** — S3 blob storage backed by ``navigator.utils.file.s3.S3FileManager``.
- **`GCSBlobStorage(_ManagerBackedBlobStorage)`** — GCS blob storage backed by ``navigator.utils.file.gcs.GCSFileManager``.
- **`LocalBlobStorage(_ManagerBackedBlobStorage)`** — Local filesystem blob storage backed by ``LocalFileManager``.
- **`TempBlobStorage(_ManagerBackedBlobStorage)`** — Ephemeral blob storage backed by ``TempFileManager``.
