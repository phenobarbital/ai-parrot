---
type: Concept
title: resolve_opaque_source()
id: func:parrot.tools.dataset_manager.sources.opaque.resolve_opaque_source
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract resource identifiers from non-SQL DataSource subclasses.
---

# resolve_opaque_source

```python
def resolve_opaque_source(source: 'DataSource') -> 'PhysicalResources'
```

Extract resource identifiers from non-SQL DataSource subclasses.

Uses ``isinstance`` dispatch per source type.  All imports are
conditional so missing optional dependencies cause a graceful fallback
to an empty :class:`PhysicalResources` rather than an ``ImportError``.

Args:
    source: Any :class:`~parrot.tools.dataset_manager.sources.base.DataSource`
        subclass.  SQL sources are **not** handled here; they belong to the
        main resolver.

Returns:
    :class:`PhysicalResources` with ``source_type`` and ``source_id``
    populated for known source types, or empty for unrecognised types.
