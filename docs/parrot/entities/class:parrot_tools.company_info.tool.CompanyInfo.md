---
type: Wiki Entity
title: CompanyInfo
id: class:parrot_tools.company_info.tool.CompanyInfo
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structured output model for company information.
---

# CompanyInfo

Defined in [`parrot_tools.company_info.tool`](../summaries/mod:parrot_tools.company_info.tool.md).

```python
class CompanyInfo(BaseModel)
```

Structured output model for company information.
Homogenized across all scraping platforms.

## Methods

- `def to_json(self, **kwargs) -> str` — Convert to JSON string.
- `def from_dict(cls, data: Dict[str, Any]) -> 'CompanyInfo'` — Create from dictionary.
