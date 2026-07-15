---
type: Wiki Entity
title: TempBlobStorage
id: class:parrot_formdesigner.services.blob_storage.TempBlobStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Ephemeral blob storage backed by ``TempFileManager``.
---

# TempBlobStorage

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class TempBlobStorage(_ManagerBackedBlobStorage)
```

Ephemeral blob storage backed by ``TempFileManager``.

Default lazy backend when no ``app["blob_storage"]`` is configured.
Useful for tests and local development: never talks to S3/GCS, never
needs credentials, and cleans itself up on process exit.

blob_ref format::

    temp://<prefix><form_id>/<field_id>/<uuid>

Args:
    prefix: Key prefix prepended to every blob (also passed as the
        temp-directory prefix when ``temp_dir_prefix`` is omitted).
    temp_dir_prefix: Override the temp-directory name prefix.

## Methods

- `async def get(self, blob_ref: str) -> AsyncIterator[bytes]` — Stream the blob bytes directly from disk.
