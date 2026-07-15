---
type: Concept
title: discover_from_walk()
id: func:parrot.tools.discovery.discover_from_walk
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Full discovery: walk packages and find all AbstractTool/AbstractToolkit
  subclasses.'
---

# discover_from_walk

```python
def discover_from_walk(sources: list[str] | None=None, filter_fn: Callable[[type], bool] | None=None) -> Dict[str, Type[Union[AbstractTool, AbstractToolkit]]]
```

Full discovery: walk packages and find all AbstractTool/AbstractToolkit subclasses.
Used for plugins/ where maintaining a registry is impractical.

Returns:
    Dict[tool_name, tool_class]
