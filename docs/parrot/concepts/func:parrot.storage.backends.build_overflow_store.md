---
type: Concept
title: build_overflow_store()
id: func:parrot.storage.backends.build_overflow_store
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Instantiate the overflow store specified by ``PARROT_OVERFLOW_STORE``.
---

# build_overflow_store

```python
def build_overflow_store(override: Optional[str]=None) -> OverflowStore
```

Instantiate the overflow store specified by ``PARROT_OVERFLOW_STORE``.

Defaults:
  - ``dynamodb`` backend → ``s3``
  - everything else → ``local`` (filesystem under ``PARROT_OVERFLOW_LOCAL_PATH``)

Args:
    override: Override the env-var value for this call only.

Returns:
    An ``OverflowStore`` wrapping the appropriate ``FileManagerInterface``.

Raises:
    ValueError: If the overflow store name is unknown.
