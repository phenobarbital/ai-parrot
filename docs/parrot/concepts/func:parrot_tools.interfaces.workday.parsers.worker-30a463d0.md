---
type: Concept
title: format_phone_number()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.format_phone_number
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Formats a phone number from various formats to the required standards.
---

# format_phone_number

```python
def format_phone_number(phone_raw: Optional[str]) -> Dict[str, Optional[str]]
```

Formats a phone number from various formats to the required standards.

Args:
    phone_raw: Phone number in any format

Returns:
    Dict with the following fields:
    - phone: Number in E164 format without spaces (e.g. 19392726591)
    - phone_area_code: Area code (e.g. 939)
    - phone_number_wo_area: Number without area code (e.g. 2726591)
    - phone_traditional: Traditional format +X (XXX) XXXXXXX
    - phone_national: National format (XXX) XXX-XXXX
    - phone_international: International format +X XXX-XXX-XXXX
    - phone_tenant: Same as phone_traditional
