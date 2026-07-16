---
type: Concept
title: build_invoke_failed_attrs()
id: func:parrot.observability.attributes.build_invoke_failed_attrs
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build OTel attributes for ``InvokeFailedEvent`` (agent root span error end).
---

# build_invoke_failed_attrs

```python
def build_invoke_failed_attrs(event: InvokeFailedEvent) -> dict[str, Any]
```

Build OTel attributes for ``InvokeFailedEvent`` (agent root span error end).

Args:
    event: The ``InvokeFailedEvent`` instance.

Returns:
    Dict of parrot-specific + OTel error attribute key-value pairs.
