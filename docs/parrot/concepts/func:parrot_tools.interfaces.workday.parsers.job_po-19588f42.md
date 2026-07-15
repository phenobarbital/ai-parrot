---
type: Concept
title: parse_site_type_data()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers.parse_site_type_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Site Type Reference data.
---

# parse_site_type_data

```python
def parse_site_type_data(site_type_ref: Dict) -> Dict[str, str]
```

Parse Site Type Reference data.

Args:
    site_type_ref: Site Type Reference from the response

Returns:
    Dictionary with site_type_id and site_type
