---
type: Wiki Entity
title: BasePlanRegistry
id: class:parrot_tools.scraping.base_registry.BasePlanRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generic disk-backed plan registry with 3-tier URL lookup.
---

# BasePlanRegistry

Defined in [`parrot_tools.scraping.base_registry`](../summaries/mod:parrot_tools.scraping.base_registry.md).

```python
class BasePlanRegistry(Generic[T])
```

Generic disk-backed plan registry with 3-tier URL lookup.

Provides load/save, lookup (exact → path-prefix → domain), register,
touch, remove, and invalidate operations against a JSON index file on
disk.  All write operations are guarded by an ``asyncio.Lock``.

Subclasses should override ``register`` if they need plan-type-specific
index entry construction.

Args:
    plans_dir: Directory for plan files and the index file.
        Defaults to ``scraping_plans`` in the current working directory.
    index_filename: Name of the JSON index file inside ``plans_dir``.
        Defaults to ``registry.json``.

## Methods

- `async def load(self) -> None` — Load registry index from disk.
- `def lookup(self, url: str, *, allow_domain_fallback: bool=True) -> Optional[PlanRegistryEntry]` — Three-tier lookup: exact fingerprint -> path-prefix -> domain.
- `def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]` — Look up an entry by plan name.
- `def list_all(self) -> List[PlanRegistryEntry]` — Return all registry entries.
- `async def register(self, plan: T, relative_path: str) -> None` — Register a plan in the index and persist to disk.
- `async def touch(self, fingerprint: str) -> None` — Update last_used_at and increment use_count for an entry.
- `async def remove(self, name: str) -> bool` — Remove an entry by name.
- `async def invalidate(self, fingerprint: str) -> None` — Invalidate and remove an entry by fingerprint.
