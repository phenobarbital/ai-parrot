---
type: Concept
title: deserialize()
id: func:parrot.outputs.a2ui.serialization.deserialize
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deserialize wire JSON into the correct concrete A2UI message.
---

# deserialize

```python
def deserialize(data: dict[str, Any] | str | bytes) -> A2UIMessageBase
```

Deserialize wire JSON into the correct concrete A2UI message.

The ``version`` field, if present, is type-checked (must be a string) and stripped
before model validation so that it never leaks onto a model instance. Its *value* is
intentionally NOT asserted equal to :data:`A2UI_VERSION` — forward/backward
compatibility (absorbing a future protocol revision) is owned by this single module,
so accepting a differing version string here is deliberate.

Args:
    data: A JSON dict, or a JSON string/bytes payload.

Returns:
    The concrete message routed via the ``messageType`` discriminator.

Raises:
    pydantic.ValidationError: If the payload is not a valid, known message.
    ValueError: If ``version`` is present but not a string.
