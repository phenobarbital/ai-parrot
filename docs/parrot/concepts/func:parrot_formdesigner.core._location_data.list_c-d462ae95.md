---
type: Concept
title: list_country_options()
id: func:parrot_formdesigner.core._location_data.list_country_options
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return all countries as a FieldOption list sorted by name.
---

# list_country_options

```python
def list_country_options() -> list[FieldOption]
```

Return all countries as a FieldOption list sorted by name.

Returns:
    List of FieldOption with value=alpha_2, label=name, icon=flag emoji.
    Returns an empty list if pycountry is not installed.
