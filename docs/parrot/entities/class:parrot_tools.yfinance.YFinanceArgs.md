---
type: Wiki Entity
title: YFinanceArgs
id: class:parrot_tools.yfinance.YFinanceArgs
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Argument schema for :class:`YFinanceTool`.
relates_to:
- concept: class:parrot.tools.abstract.AbstractToolArgsSchema
  rel: extends
---

# YFinanceArgs

Defined in [`parrot_tools.yfinance`](../summaries/mod:parrot_tools.yfinance.md).

```python
class YFinanceArgs(AbstractToolArgsSchema)
```

Argument schema for :class:`YFinanceTool`.

## Methods

- `def normalize_ticker(cls, value: str) -> str`
