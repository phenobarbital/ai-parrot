---
type: Wiki Entity
title: WorkingMemoryCatalog
id: class:parrot.tools.working_memory.internals.WorkingMemoryCatalog
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory catalog of DataFrames and generic entries.
---

# WorkingMemoryCatalog

Defined in [`parrot.tools.working_memory.internals`](../summaries/mod:parrot.tools.working_memory.internals.md).

```python
class WorkingMemoryCatalog
```

In-memory catalog of DataFrames and generic entries.

Session-scoped storage engine that supports both DataFrame-centric
``CatalogEntry`` objects and polymorphic ``GenericEntry`` objects.

Key namespace is shared: storing either type with an existing key replaces
the previous entry regardless of its type. This is intentional.

## Methods

- `def put(self, key: str, df: pd.DataFrame, *, operation: Optional[OperationSpecInput]=None, parent_keys: Optional[list[str]]=None, description: str='', error: Optional[str]=None, turn_id: Optional[str]=None) -> CatalogEntry` — Store a DataFrame under the given key and return the catalog entry.
- `def put_generic(self, key: str, data: Any, *, entry_type: Optional[EntryType]=None, description: str='', metadata: Optional[dict]=None, turn_id: Optional[str]=None) -> GenericEntry` — Store arbitrary data under the given key and return the GenericEntry.
- `def get(self, key: str) -> CatalogEntry | GenericEntry` — Retrieve a catalog entry by key.
- `def drop(self, key: str) -> bool` — Remove an entry by key. Returns True if the key existed.
- `def list_entries(self, turn_id: Optional[str]=None, shape_limit: Optional[ShapeLimit]=None) -> list[dict]` — Return compact summaries of all stored entries, optionally filtered by turn_id.
- `def keys(self) -> list[str]` — Return all stored keys.
