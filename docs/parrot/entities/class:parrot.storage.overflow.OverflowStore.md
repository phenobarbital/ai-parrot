---
type: Wiki Entity
title: OverflowStore
id: class:parrot.storage.overflow.OverflowStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generic artifact overflow store backed by any FileManagerInterface.
---

# OverflowStore

Defined in [`parrot.storage.overflow`](../summaries/mod:parrot.storage.overflow.md).

```python
class OverflowStore
```

Generic artifact overflow store backed by any FileManagerInterface.

If an artifact's serialised definition is smaller than
``INLINE_THRESHOLD`` (200 KB), it stays inline in the storage backend.
Otherwise the JSON is uploaded via the file manager and only the
reference key is stored.

Args:
    file_manager: Any ``FileManagerInterface`` implementation
        (S3, GCS, Local, Temp).

## Methods

- `async def maybe_offload(self, data: Dict[str, Any], key_prefix: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]` — Decide whether *data* fits inline or must be offloaded.
- `async def resolve(self, definition: Optional[Dict[str, Any]], definition_ref: Optional[str]) -> Optional[Dict[str, Any]]` — Resolve an artifact definition, fetching from file manager if needed.
- `async def generate_presigned_url(self, key: str, *, expires_in: int=604800) -> str` — Generate a presigned URL for an overflow object.
- `async def delete(self, definition_ref: Optional[str]) -> bool` — Delete the file for ``definition_ref`` if it exists.
