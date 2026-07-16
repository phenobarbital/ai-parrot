---
type: Concept
title: build_after_invoke_attrs()
id: func:parrot.observability.attributes.build_after_invoke_attrs
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build OTel attributes for ``AfterInvokeEvent`` (agent root span end).
---

# build_after_invoke_attrs

```python
def build_after_invoke_attrs(event: AfterInvokeEvent) -> dict[str, Any]
```

Build OTel attributes for ``AfterInvokeEvent`` (agent root span end).

Args:
    event: The ``AfterInvokeEvent`` instance.

Returns:
    Dict of OTel attribute key-value pairs.
