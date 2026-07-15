---
type: Concept
title: build_after_client_attrs()
id: func:parrot.observability.attributes.build_after_client_attrs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build OTel attributes for ``AfterClientCallEvent`` (client child span end).
---

# build_after_client_attrs

```python
def build_after_client_attrs(event: AfterClientCallEvent, *, cost_usd: Optional[float]=None) -> dict[str, Any]
```

Build OTel attributes for ``AfterClientCallEvent`` (client child span end).

Args:
    event: The ``AfterClientCallEvent`` instance.
    cost_usd: Optional computed cost in USD from ``CostCalculator``.
        Omitted from attrs when ``None``.

Returns:
    Dict of GenAI SemConv + parrot-specific OTel attribute key-value pairs.
