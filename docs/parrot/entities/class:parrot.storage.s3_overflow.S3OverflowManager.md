---
type: Wiki Entity
title: S3OverflowManager
id: class:parrot.storage.s3_overflow.S3OverflowManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Back-compat subclass: OverflowStore bound to S3FileManager.'
relates_to:
- concept: class:parrot.storage.overflow.OverflowStore
  rel: extends
---

# S3OverflowManager

Defined in [`parrot.storage.s3_overflow`](../summaries/mod:parrot.storage.s3_overflow.md).

```python
class S3OverflowManager(OverflowStore)
```

Back-compat subclass: OverflowStore bound to S3FileManager.

Preserves the original constructor signature so existing callers do not
need to change. The class now delegates all behaviour to ``OverflowStore``
which accepts any ``FileManagerInterface``.

Args:
    s3_file_manager: Pre-configured ``S3FileManager`` pointing at
        the artifact bucket.
