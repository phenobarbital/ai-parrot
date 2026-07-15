---
type: Concept
title: parse_organizations_response()
id: func:parrot_tools.interfaces.workday.parsers.organization_parsers.parse_organizations_response
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse the complete organizations response from Workday.
---

# parse_organizations_response

```python
def parse_organizations_response(response_data: Dict[str, Any]) -> List[Organization]
```

Parse the complete organizations response from Workday.

:param response_data: Raw response data from Workday
:return: List of parsed Organization models
