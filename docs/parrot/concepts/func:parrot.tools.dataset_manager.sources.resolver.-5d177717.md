---
type: Concept
title: resolve_physical_resources()
id: func:parrot.tools.dataset_manager.sources.resolver.resolve_physical_resources
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve a DataSource to the set of physical resources it will touch.
---

# resolve_physical_resources

```python
def resolve_physical_resources(source: 'DataSource') -> PhysicalResources
```

Resolve a DataSource to the set of physical resources it will touch.

Dispatches on the source type:
- :class:`~parrot.tools.dataset_manager.sources.sql.SQLQuerySource`:
  sqlglot parse + table extraction.
- :class:`~parrot.tools.dataset_manager.sources.table.TableSource`:
  trivial single-table extraction.
- :class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`:
  returns empty (slug grants handled separately).
- :class:`~parrot.tools.dataset_manager.sources.memory.InMemorySource`:
  returns empty (no driver round-trip).
- All other sources: delegates to :mod:`.opaque` resolver.

Args:
    source: Any :class:`~parrot.tools.dataset_manager.sources.base.DataSource`
        subclass.

Returns:
    A :class:`PhysicalResources` describing what the source accesses.
