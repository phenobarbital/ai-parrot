---
type: Concept
title: build_client_failed_attrs()
id: func:parrot.observability.attributes.build_client_failed_attrs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build OTel attributes for ``ClientCallFailedEvent`` (client error span end).
---

# build_client_failed_attrs

```python
def build_client_failed_attrs(event: ClientCallFailedEvent) -> dict[str, Any]
```

Build OTel attributes for ``ClientCallFailedEvent`` (client error span end).

Args:
    event: The ``ClientCallFailedEvent`` instance.

Returns:
    Dict of OTel error + GenAI SemConv attribute key-value pairs.
