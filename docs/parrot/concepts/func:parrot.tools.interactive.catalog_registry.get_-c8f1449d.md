---
type: Concept
title: get_interactive_catalog()
id: func:parrot.tools.interactive.catalog_registry.get_interactive_catalog
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the process-wide catalog singleton (not yet loaded).
---

# get_interactive_catalog

```python
def get_interactive_catalog() -> InteractiveCatalogRegistry
```

Return the process-wide catalog singleton (not yet loaded).

The catalog is loaded on first access via ``_ensure_loaded()`` (sync) or
``ensure_loaded_async()`` (async, thread-safe).  Async callers should call
``await catalog.ensure_loaded_async()`` before touching catalog data to
avoid blocking the event loop with disk I/O.
