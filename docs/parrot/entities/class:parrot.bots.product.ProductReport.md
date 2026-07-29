---
type: Wiki Entity
title: ProductReport
id: class:parrot.bots.product.ProductReport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ProductReport is an agent designed to generate detailed product reports using
  LLMs and various tools.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# ProductReport

Defined in [`parrot.bots.product`](../summaries/mod:parrot.bots.product.md).

```python
class ProductReport(BasicAgent)
```

ProductReport is an agent designed to generate detailed product reports using LLMs and various tools.

## Methods

- `async def create_product_report(self, program_slug: str, models: Optional[List[str]]=None) -> List[ProductResponse]` — Create product reports for products in a given program/tenant.
