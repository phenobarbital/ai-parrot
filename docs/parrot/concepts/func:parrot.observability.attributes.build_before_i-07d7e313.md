---
type: Concept
title: build_before_invoke_attrs()
id: func:parrot.observability.attributes.build_before_invoke_attrs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build OTel attributes for ``BeforeInvokeEvent`` (agent root span start).
---

# build_before_invoke_attrs

```python
def build_before_invoke_attrs(event: BeforeInvokeEvent) -> dict[str, Any]
```

Build OTel attributes for ``BeforeInvokeEvent`` (agent root span start).

Args:
    event: The ``BeforeInvokeEvent`` instance.

Returns:
    Dict of OTel attribute key-value pairs. Never contains PII.
