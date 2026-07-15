---
type: Wiki Entity
title: DocumentDbResultStorage
id: class:parrot.bots.flows.core.storage.backends.documentdb.DocumentDbResultStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Default backend — preserves the legacy DocumentDB write path.
relates_to:
- concept: class:parrot.bots.flows.core.storage.backends.base.ResultStorage
  rel: extends
---

# DocumentDbResultStorage

Defined in [`parrot.bots.flows.core.storage.backends.documentdb`](../summaries/mod:parrot.bots.flows.core.storage.backends.documentdb.md).

```python
class DocumentDbResultStorage(ResultStorage)
```

Default backend — preserves the legacy DocumentDB write path.

Each ``save()`` call opens a fresh ``async with DocumentDb()`` context,
matching the existing fire-and-forget semantics. ``close()`` is a no-op
because the connection lifecycle is owned per-write.

## Methods

- `async def save(self, collection: str, document: dict[str, Any]) -> None` — Persist a document to DocumentDB.
- `async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]` — Return all documents in *collection* whose ``execution_id`` matches.
- `async def close(self) -> None` — No-op — connection lifecycle is per-write in this backend.
- `async def list(self, collection: str, filters: Optional[dict[str, Any]]=None, limit: int=20, offset: int=0) -> list[dict[str, Any]]` — List execution documents ordered by ``timestamp DESC``.
- `async def get(self, collection: str, record_id: str) -> Optional[dict[str, Any]]` — Retrieve a single execution document by its ``record_id``.
- `async def delete(self, collection: str, record_id: str) -> bool` — Delete a single execution document by its ``record_id``.
- `async def count(self, collection: str, filters: Optional[dict[str, Any]]=None) -> int` — Count execution documents matching the given filters.
