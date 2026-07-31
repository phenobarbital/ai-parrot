---
type: Concept
title: is_valid_iso_country_code()
id: func:parrot_formdesigner.core._location_data.is_valid_iso_country_code
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return True if code is a valid ISO 3166-1 alpha-2 country code.
---

# is_valid_iso_country_code

```python
def is_valid_iso_country_code(code: str) -> bool
```

Return True if code is a valid ISO 3166-1 alpha-2 country code.

Args:
    code: Two-letter country code (case-insensitive).

Returns:
    True if valid, False otherwise. Returns True if pycountry is not installed.
