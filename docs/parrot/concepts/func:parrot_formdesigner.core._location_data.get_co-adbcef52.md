---
type: Concept
title: get_country_info()
id: func:parrot_formdesigner.core._location_data.get_country_info
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return name, flag emoji, and dial code for a country code.
---

# get_country_info

```python
def get_country_info(code: str) -> dict | None
```

Return name, flag emoji, and dial code for a country code.

Args:
    code: ISO 3166-1 alpha-2 country code.

Returns:
    Dict with keys 'name', 'flag', 'dial_code', or None if not found
    or if pycountry is not installed.
