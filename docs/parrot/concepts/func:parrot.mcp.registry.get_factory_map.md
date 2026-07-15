---
type: Concept
title: get_factory_map()
id: func:parrot.mcp.registry.get_factory_map
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the dispatch map from registry slug to ``create_*`` factory function.
---

# get_factory_map

```python
def get_factory_map() -> Dict[str, Any]
```

Return the dispatch map from registry slug to ``create_*`` factory function.

Deferred import to avoid circular dependencies (the factory functions live
in ``parrot.mcp.integration`` which may import from this module).
