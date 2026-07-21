---
type: Concept
title: build_before_tool_attrs()
id: func:parrot.observability.attributes.build_before_tool_attrs
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build OTel attributes for ``BeforeToolCallEvent`` (tool child span start).
---

# build_before_tool_attrs

```python
def build_before_tool_attrs(event: BeforeToolCallEvent) -> dict[str, Any]
```

Build OTel attributes for ``BeforeToolCallEvent`` (tool child span start).

Args:
    event: The ``BeforeToolCallEvent`` instance.

Returns:
    Dict of parrot-specific OTel attribute key-value pairs.
