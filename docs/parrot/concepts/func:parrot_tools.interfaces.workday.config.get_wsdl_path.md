---
type: Concept
title: get_wsdl_path()
id: func:parrot_tools.interfaces.workday.config.get_wsdl_path
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the WSDL path for a given Workday operation type.
---

# get_wsdl_path

```python
def get_wsdl_path(operation_type: str) -> Any
```

Return the WSDL path for a given Workday operation type.

Falls back to ``WORKDAY_WSDL_PATH`` (staffing WSDL) for unknown types,
matching the behaviour of ``workday.py:360`` and ``workday.py:517``.

Args:
    operation_type: The Workday operation key (e.g. ``"get_workers"``).

Returns:
    The resolved WSDL path (``str`` or ``pathlib.Path`` depending on
    whether the value was loaded from the config file or the fallback).
