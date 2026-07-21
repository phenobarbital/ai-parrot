---
type: Wiki Entity
title: ProductLoader
id: class:parrot.advisors.catalog.loaders.ProductLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base loader for product data.
---

# ProductLoader

Defined in [`parrot.advisors.catalog.loaders`](../summaries/mod:parrot.advisors.catalog.loaders.md).

```python
class ProductLoader
```

Base loader for product data.

Override _parse_product() for custom formats.

## Methods

- `async def load_file(self, file_path: Union[str, Path]) -> LoadResult` — Load products from a JSON file.
- `async def load_products(self, products_data: List[Dict[str, Any]]) -> LoadResult` — Load multiple products from parsed data.
