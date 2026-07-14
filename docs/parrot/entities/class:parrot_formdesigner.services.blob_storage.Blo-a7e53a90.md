---
type: Wiki Entity
title: BlobRejectedError
id: class:parrot_formdesigner.services.blob_storage.BlobRejectedError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised by ``AbstractBlobStorage.pre_persist_hook`` to abort a ``put``.
---

# BlobRejectedError

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class BlobRejectedError(Exception)
```

Raised by ``AbstractBlobStorage.pre_persist_hook`` to abort a ``put``.

Subclasses may raise this from their hook implementation to prevent the
blob from being persisted. The upload handler will propagate this error
to the caller.
