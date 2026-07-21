---
type: Wiki Summary
title: parrot_tools.yfinance
id: mod:parrot_tools.yfinance
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: YFinance tool for retrieving market data via Yahoo Finance.
relates_to:
- concept: class:parrot_tools.yfinance.YFinanceArgs
  rel: defines
- concept: class:parrot_tools.yfinance.YFinanceTool
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.cache
  rel: references
---

# `parrot_tools.yfinance`

YFinance tool for retrieving market data via Yahoo Finance.

## Classes

- **`YFinanceArgs(AbstractToolArgsSchema)`** — Argument schema for :class:`YFinanceTool`.
- **`YFinanceTool(AbstractTool)`** — Retrieve quotes, company information, and financial statements via Yahoo Finance.
