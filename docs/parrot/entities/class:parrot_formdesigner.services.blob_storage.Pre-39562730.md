---
type: Wiki Entity
title: PrePersistContext
id: class:parrot_formdesigner.services.blob_storage.PrePersistContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Context passed to ``AbstractBlobStorage.pre_persist_hook`` before writing.
---

# PrePersistContext

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class PrePersistContext(BaseModel)
```

Context passed to ``AbstractBlobStorage.pre_persist_hook`` before writing.

In V1 the default ``pre_persist_hook`` is a no-op. V2 will use this
context to perform AV/content-scanning before persisting the blob.

Attributes:
    metadata: Full blob metadata.
    content_preview: First N bytes of the content for scanning.
        ``None`` disables preview-based scanning.
