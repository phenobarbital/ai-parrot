---
type: Concept
title: discover_from_registry()
id: func:parrot.tools.discovery.discover_from_registry
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Fast discovery: read TOOL_REGISTRY dicts from package __init__.py.'
---

# discover_from_registry

```python
def discover_from_registry(sources: list[str] | None=None) -> Dict[str, str]
```

Fast discovery: read TOOL_REGISTRY dicts from package __init__.py.

Returns:
    Dict[tool_name, dotted_path_to_class]
