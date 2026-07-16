---
type: Concept
title: finalize_a2ui_response()
id: func:parrot.outputs.a2ui.emission.finalize_a2ui_response
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Route an ``OutputMode.A2UI`` response around the legacy formatter (FEAT-273).
---

# finalize_a2ui_response

```python
def finalize_a2ui_response(response: Any) -> None
```

Route an ``OutputMode.A2UI`` response around the legacy formatter (FEAT-273).

Places the declarative envelope in ``response.a2ui_envelope`` (a plain dict), sets
``response.output_mode = OutputMode.A2UI``, and populates a human-readable fallback
in ``response.response`` — without entering ``OutputFormatter`` or serializing the
envelope into ``response.output`` (kept intact for legacy consumers).

Args:
    response: The bot response object (duck-typed: ``a2ui_envelope``/``output``/
        ``response``/``output_mode`` attributes).
