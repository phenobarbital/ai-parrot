---
type: Wiki Entity
title: FredAPITool
id: class:parrot_tools.fred_api.FredAPITool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for fetching economic data from the Federal Reserve Economic Data (FRED)
  API.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# FredAPITool

Defined in [`parrot_tools.fred_api`](../summaries/mod:parrot_tools.fred_api.md).

```python
class FredAPITool(AbstractTool)
```

Tool for fetching economic data from the Federal Reserve Economic Data (FRED) API.

This tool uses the requests-based HTTPService to interact with the FRED API
in an async manner, avoiding blocking calls.

Common endpoints:
- series/observations: Get data for a specific series.
- releases/dates: Get release dates.
