---
type: Concept
title: build_message_event_attrs()
id: func:parrot.observability.attributes.build_message_event_attrs
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build OTel span-event attributes for ``MessageAddedEvent``.
---

# build_message_event_attrs

```python
def build_message_event_attrs(event: MessageAddedEvent) -> dict[str, Any]
```

Build OTel span-event attributes for ``MessageAddedEvent``.

These are attached as span *events* (not spans) to the active invoke span.

Args:
    event: The ``MessageAddedEvent`` instance.

Returns:
    Dict of parrot-specific OTel attribute key-value pairs.
