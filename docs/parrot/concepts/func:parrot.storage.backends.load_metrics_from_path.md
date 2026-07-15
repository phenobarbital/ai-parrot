---
type: Concept
title: load_metrics_from_path()
id: func:parrot.storage.backends.load_metrics_from_path
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Import and return a ``StorageMetrics`` instance from a module path.
---

# load_metrics_from_path

```python
def load_metrics_from_path(path: str) -> 'StorageMetrics'
```

Import and return a ``StorageMetrics`` instance from a module path.

Args:
    path: Module path in ``"module.name:attribute"`` format.

Returns:
    The ``StorageMetrics`` instance at the given path.

Raises:
    RuntimeError: If the path is malformed or the import fails.
