---
type: Wiki Entity
title: ResultStorage
id: class:parrot.bots.flows.core.storage.backends.base.ResultStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract pluggable backend for crew/flow execution result persistence.
---

# ResultStorage

Defined in [`parrot.bots.flows.core.storage.backends.base`](../summaries/mod:parrot.bots.flows.core.storage.backends.base.md).

```python
class ResultStorage(ABC)
```

Abstract pluggable backend for crew/flow execution result persistence.

Implementations must be async-safe and idempotent on ``close()``.

Attributes:
    None (contract via abstract methods only).

## Methods

- `async def save(self, collection: str, document: dict[str, Any]) -> None` — Persist a single execution document.
- `async def close(self) -> None` — Release any underlying connection/pool. Safe to call multiple times.
- `async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]` — Return all documents in *collection* matching *execution_id*.
- `async def list(self, collection: str, filters: dict[str, Any] | None=None, limit: int=20, offset: int=0) -> list[dict[str, Any]]` — List persisted execution documents, newest first.
- `async def get(self, collection: str, record_id: str) -> dict[str, Any] | None` — Retrieve a single execution document by its record id.
- `async def delete(self, collection: str, record_id: str) -> bool` — Delete a single execution document by its record id.
- `async def count(self, collection: str, filters: dict[str, Any] | None=None) -> int` — Count persisted execution documents matching the given filters.
