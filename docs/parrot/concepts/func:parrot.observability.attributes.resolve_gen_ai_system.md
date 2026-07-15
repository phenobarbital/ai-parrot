---
type: Concept
title: resolve_gen_ai_system()
id: func:parrot.observability.attributes.resolve_gen_ai_system
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve a ``client_name`` emitted on ``BeforeClientCallEvent`` to the
---

# resolve_gen_ai_system

```python
def resolve_gen_ai_system(client_name: str) -> str
```

Resolve a ``client_name`` emitted on ``BeforeClientCallEvent`` to the
corresponding ``gen_ai.system`` OTel attribute value.

Args:
    client_name: Value from ``BeforeClientCallEvent.client_name``.

Returns:
    The ``gen_ai.system`` value; falls back to the raw ``client_name``
    and logs a one-time WARN for unknown providers.
