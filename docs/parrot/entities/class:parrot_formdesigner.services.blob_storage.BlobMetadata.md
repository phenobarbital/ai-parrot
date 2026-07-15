---
type: Wiki Entity
title: BlobMetadata
id: class:parrot_formdesigner.services.blob_storage.BlobMetadata
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Metadata associated with a persisted blob.
---

# BlobMetadata

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class BlobMetadata(BaseModel)
```

Metadata associated with a persisted blob.

Attributes:
    form_id: Identifier of the parent form.
    field_id: Identifier of the form field that owns this blob.
    submission_id: Optional submission ID for audit correlation.
    tenant: Optional tenant slug for multi-tenant deployments.
    content_type: MIME type of the stored content (e.g. ``image/jpeg``).
    size_bytes: Size of the content in bytes.
