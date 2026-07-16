---
type: Concept
title: build_form_schema()
id: func:parrot.auth.confirmation.build_form_schema
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a FORM interaction schema from the tool's args_schema.
---

# build_form_schema

```python
def build_form_schema(tool: 'AbstractTool', parameters: dict) -> dict
```

Build a FORM interaction schema from the tool's args_schema.

Derives a ``form_schema`` dict for a ``HumanInteraction(type=FORM)``
interaction, pre-filled with the current ``parameters`` so the human
sees the intended values and can edit them.

The produced schema passes the ``HumanInteraction`` model_validator
(non-empty dict requirement).

Args:
    tool: The tool being confirmed.
    parameters: Current call parameters (used as default values).

Returns:
    A non-empty form_schema dict suitable for ``HumanInteraction.form_schema``.
