---
type: Wiki Entity
title: BestBuyToolkit
id: class:parrot_tools.retail.bby.BestBuyToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for interacting with BestBuy API and services.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# BestBuyToolkit

Defined in [`parrot_tools.retail.bby`](../summaries/mod:parrot_tools.retail.bby.md).

```python
class BestBuyToolkit(AbstractToolkit)
```

Toolkit for interacting with BestBuy API and services.

Provides methods for:
- Searching for products
- Getting product information
- Checking store availability
- Finding nearby stores

## Methods

- `async def search_products(self, search_terms: Optional[str]=None, product_name: Optional[str]=None) -> Dict[str, Any]` — Search for products on BestBuy using product names or search terms.
- `async def check_availability(self, zipcode: str, sku: str, location_id: str, show_only_in_stock: bool=False) -> Dict[str, Any]` — Check product availability at a specific BestBuy store.
- `async def find_stores(self, zipcode: str, radius: int=25) -> Dict[str, Any]` — Find BestBuy stores near a ZIP code.
- `async def get_product_details(self, sku: str) -> Dict[str, Any]` — Get detailed information for a specific product by SKU.
