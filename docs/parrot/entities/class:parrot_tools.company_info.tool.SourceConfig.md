---
type: Wiki Entity
title: SourceConfig
id: class:parrot_tools.company_info.tool.SourceConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Internal per-source search configuration.
---

# SourceConfig

Defined in [`parrot_tools.company_info.tool`](../summaries/mod:parrot_tools.company_info.tool.md).

```python
class SourceConfig(BaseModel)
```

Internal per-source search configuration.

NOT a tool schema — used by `_search_company_url`/`_validate_search_hit`
to know how to search and validate hits for a given source. Templates and
title keywords are ported from flowtask's `CompanyScraper` parsers.
