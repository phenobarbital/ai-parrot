---
type: Concept
title: current_credential()
id: func:parrot.tools.abstract.current_credential
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the per-call credential injected by the broker, or ``None``.
---

# current_credential

```python
def current_credential() -> Optional[Any]
```

Return the per-call credential injected by the broker, or ``None``.

Tools that declare ``credential_provider`` can call this inside
``_execute()`` to obtain the resolved per-user credential material.
The value is set by the tool-loop seam (FEAT-264) just before
``_execute()`` is called and reset in the ``finally`` block.

Returns:
    The resolved credential (token, API-key dict, …) or ``None`` if
    not in a credentialed execution context.
