---
type: Concept
title: build_tool_failed_attrs()
id: func:parrot.observability.attributes.build_tool_failed_attrs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build OTel attributes for ``ToolCallFailedEvent`` (tool error span end).
---

# build_tool_failed_attrs

```python
def build_tool_failed_attrs(event: ToolCallFailedEvent) -> dict[str, Any]
```

Build OTel attributes for ``ToolCallFailedEvent`` (tool error span end).

Args:
    event: The ``ToolCallFailedEvent`` instance.

Returns:
    Dict of parrot-specific + OTel error attribute key-value pairs.
