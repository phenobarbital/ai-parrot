---
type: Concept
title: sanitize_phone_number()
id: func:parrot.integrations.whatsapp.utils.sanitize_phone_number
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Normalize a phone number by stripping non-digit characters.
---

# sanitize_phone_number

```python
def sanitize_phone_number(number: str) -> str
```

Normalize a phone number by stripping non-digit characters.

Args:
    number: Phone number string (may contain +, spaces, dashes).

Returns:
    Cleaned phone number string with only digits.
