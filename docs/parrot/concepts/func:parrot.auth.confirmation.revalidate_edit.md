---
type: Concept
title: revalidate_edit()
id: func:parrot.auth.confirmation.revalidate_edit
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate edited values against the tool's args_schema.
---

# revalidate_edit

```python
def revalidate_edit(tool: 'AbstractTool', edited: dict) -> dict
```

Validate edited values against the tool's args_schema.

Args:
    tool: The tool being confirmed (provides ``args_schema``).
    edited: The edited parameter dict returned by the human.

Returns:
    Validated (and possibly coerced) parameter dict.

Raises:
    ValidationError: If the edited values do not pass schema validation.
