---
type: Concept
title: serialize()
id: func:parrot.outputs.a2ui.serialization.serialize
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Serialize an A2UI message to a JSON-ready dict, injecting ``version``.
---

# serialize

```python
def serialize(message: A2UIMessageBase) -> dict[str, Any]
```

Serialize an A2UI message to a JSON-ready dict, injecting ``version``.

Args:
    message: Any concrete A2UI message instance.

Returns:
    A dict using the wire (aliased) field names, with ``version`` set to
    :data:`A2UI_VERSION`.
