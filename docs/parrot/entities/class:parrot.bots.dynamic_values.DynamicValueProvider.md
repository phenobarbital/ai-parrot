---
type: Wiki Entity
title: DynamicValueProvider
id: class:parrot.bots.dynamic_values.DynamicValueProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Registry for dynamic value functions
---

# DynamicValueProvider

Defined in [`parrot.bots.dynamic_values`](../summaries/mod:parrot.bots.dynamic_values.md).

```python
class DynamicValueProvider
```

Registry for dynamic value functions

## Methods

- `def register(self, name: str)` — Decorator to register a dynamic value provider
- `async def get_value(self, name: str, context: Dict[str, Any]=None) -> Any` — Get a dynamic value, passing runtime context
- `def get_all_names(self)` — Return list of all registered value names
