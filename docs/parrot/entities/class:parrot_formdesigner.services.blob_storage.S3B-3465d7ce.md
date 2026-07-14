---
type: Wiki Entity
title: S3BlobStorage
id: class:parrot_formdesigner.services.blob_storage.S3BlobStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: S3 blob storage backed by ``navigator.utils.file.s3.S3FileManager``.
---

# S3BlobStorage

Defined in [`parrot_formdesigner.services.blob_storage`](../summaries/mod:parrot_formdesigner.services.blob_storage.md).

```python
class S3BlobStorage(_ManagerBackedBlobStorage)
```

S3 blob storage backed by ``navigator.utils.file.s3.S3FileManager``.

Credentials are resolved by ``S3FileManager`` using ``AWS_CREDENTIALS``
from ``parrot.conf`` keyed by ``aws_id`` (default ``"default"``), or an
explicit ``credentials`` dict passed through. Bucket resolution falls
back to ``PARROT_BLOB_BUCKET`` for backward compatibility, then to the
credential profile's ``bucket_name``.

blob_ref format::

    s3://<bucket>/<prefix><form_id>/<field_id>/<uuid>

Args:
    bucket: S3 bucket name. Falls back to ``PARROT_BLOB_BUCKET`` env var
        and then to ``AWS_CREDENTIALS[aws_id]["bucket_name"]``.
    prefix: Key prefix prepended to every blob. Falls back to
        ``PARROT_BLOB_PREFIX``. Defaults to ``""``.
    aws_id: Name of the profile in ``AWS_CREDENTIALS`` (default
        ``"default"``).
    region_name: AWS region override.
    credentials: Explicit credentials dict (``{"aws_key": ..., "aws_secret": ...}``).
        Bypasses ``AWS_CREDENTIALS`` lookup when provided.

Raises:
    RuntimeError: If no bucket can be resolved.

## Methods

- `def bucket(self) -> str`
- `def prefix(self) -> str`
