---
type: Wiki Entity
title: PricesTool
id: class:parrot_tools.pricestool.PricesTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for querying product prices from a database or API.
relates_to:
- concept: class:parrot_tools.querytoolkit.QueryToolkit
  rel: extends
---

# PricesTool

Defined in [`parrot_tools.pricestool`](../summaries/mod:parrot_tools.pricestool.md).

```python
class PricesTool(QueryToolkit)
```

Tool for querying product prices from a database or API.

## Methods

- `async def get_model_price(self, tenant: str, model: str, week: int, output_format: str='structured') -> PriceOutput` — Fetches the price of a product for a given tenant, model, and week.
- `async def get_weekly_price(self, tenant: str, week: int, limit: int=10, output_format: str='structured') -> List[PriceOutput]` — Fetches all product prices for a given tenant and week.
- `async def get_price(self, tenant: str, start_date: str, end_date: str, limit: int=10, output_format: str='structured') -> List[PriceOutput]` — Fetches all product prices for a given tenant and date range.
