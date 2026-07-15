---
type: Wiki Entity
title: LocalBlobStorage
id: class:parrot_formdesigner.services.blob_storage.LocalBlobStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Local filesystem blob storage backed by ``LocalFileManager``.
---

# LocalBlobStorage

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class LocalBlobStorage(_ManagerBackedBlobStorage)
```

Local filesystem blob storage backed by ``LocalFileManager``.

Suitable for single-host deployments or development environments. All
blobs live under a single ``base_path`` directory sandboxed by the
underlying ``LocalFileManager``.

blob_ref format::

    file://<prefix><form_id>/<field_id>/<uuid>

The path is relative to the manager's ``base_path`` — refs are only
valid against the same ``LocalBlobStorage`` configuration that produced
them.

Args:
    base_path: Root directory for blob storage. Falls back to
        ``PARROT_BLOB_PATH`` env var, then to ``"./blobs"``.
    prefix: Key prefix prepended to every blob.
