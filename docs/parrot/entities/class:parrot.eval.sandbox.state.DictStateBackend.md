---
type: Wiki Entity
title: DictStateBackend
id: class:parrot.eval.sandbox.state.DictStateBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'In-memory ``{collection: {entity_id: {field: value}}}`` store.'
relates_to:
- concept: class:parrot.eval.sandbox.state.StateBackend
  rel: extends
---

# DictStateBackend

Defined in [`parrot.eval.sandbox.state`](../summaries/mod:parrot.eval.sandbox.state.md).

```python
class DictStateBackend(StateBackend)
```

In-memory ``{collection: {entity_id: {field: value}}}`` store.

Provides CRUD-ish helpers used by fake database / Jira drivers:
``create``, ``get``, ``update``, ``delete``, ``list``, ``query``.

Snapshots are:
- **deep copies** — callers cannot mutate internal state.
- **deterministic** — collections and entity keys are sorted.

## Methods

- `async def reset(self, seed_state: dict[str, Any] | None) -> None` — Reset the store.
- `async def snapshot(self) -> dict[str, Any]` — Return a sorted, deep-copied snapshot of the current state.
- `async def create(self, collection: str, entity_id: str, fields: dict[str, Any]) -> None` — Insert a new entity.
- `async def get(self, collection: str, entity_id: str) -> dict[str, Any] | None` — Fetch a single entity by id.
- `async def update(self, collection: str, entity_id: str, fields: dict[str, Any]) -> None` — Merge *fields* into an existing entity (partial update).
- `async def delete(self, collection: str, entity_id: str) -> bool` — Remove an entity.
- `async def list(self, collection: str) -> list[dict[str, Any]]` — Return all entities in a collection as a list of dicts.
- `async def query(self, collection: str, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]` — Return entities in *collection* where *predicate* returns ``True``.
- `async def upsert(self, collection: str, entity_id: str, fields: dict[str, Any]) -> None` — Insert or update an entity.
