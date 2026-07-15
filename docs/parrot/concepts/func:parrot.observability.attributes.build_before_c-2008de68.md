---
type: Concept
title: build_before_client_attrs()
id: func:parrot.observability.attributes.build_before_client_attrs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build OTel attributes for ``BeforeClientCallEvent`` (client child span start).
---

# build_before_client_attrs

```python
def build_before_client_attrs(event: BeforeClientCallEvent) -> dict[str, Any]
```

Build OTel attributes for ``BeforeClientCallEvent`` (client child span start).

Follows GenAI SemConv. Omits any field that is None.

Args:
    event: The ``BeforeClientCallEvent`` instance.

Returns:
    Dict of GenAI SemConv + parrot-specific OTel attribute key-value pairs.
