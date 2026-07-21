---
type: Concept
title: build_after_tool_attrs()
id: func:parrot.observability.attributes.build_after_tool_attrs
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build OTel attributes for ``AfterToolCallEvent`` (tool child span end).
---

# build_after_tool_attrs

```python
def build_after_tool_attrs(event: AfterToolCallEvent) -> dict[str, Any]
```

Build OTel attributes for ``AfterToolCallEvent`` (tool child span end).

Args:
    event: The ``AfterToolCallEvent`` instance.

Returns:
    Dict of parrot-specific OTel attribute key-value pairs.
