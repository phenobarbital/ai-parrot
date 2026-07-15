---
type: Concept
title: parse_organization_data()
id: func:parrot_tools.interfaces.workday.parsers.organization_parsers.parse_organization_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse organization data from Workday SOAP response.
---

# parse_organization_data

```python
def parse_organization_data(org_data: Union[Dict[str, Any], OrderedDict]) -> Organization
```

Parse organization data from Workday SOAP response.

:param org_data: Raw organization data from Workday
:return: Parsed Organization model
