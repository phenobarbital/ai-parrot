---
type: Wiki Entity
title: GCSBlobStorage
id: class:parrot_formdesigner.services.blob_storage.GCSBlobStorage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: GCS blob storage backed by ``navigator.utils.file.gcs.GCSFileManager``.
---

# GCSBlobStorage

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class GCSBlobStorage(_ManagerBackedBlobStorage)
```

GCS blob storage backed by ``navigator.utils.file.gcs.GCSFileManager``.

blob_ref format::

    gs://<bucket>/<prefix><form_id>/<field_id>/<uuid>

Args:
    bucket: GCS bucket name.
    prefix: Key prefix prepended to every blob.
    **manager_kwargs: Forwarded to ``GCSFileManager`` (e.g.
        ``project_id``, ``credentials_path``).

Raises:
    RuntimeError: If no bucket is provided.
