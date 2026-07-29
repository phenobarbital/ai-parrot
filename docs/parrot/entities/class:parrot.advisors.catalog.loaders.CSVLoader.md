---
type: Wiki Entity
title: CSVLoader
id: class:parrot.advisors.catalog.loaders.CSVLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Loader for CSV product data.
relates_to:
- concept: class:parrot.advisors.catalog.loaders.ProductLoader
  rel: extends
---

# CSVLoader

Defined in [`parrot.advisors.catalog.loaders`](../summaries/mod:parrot.advisors.catalog.loaders.md).

```python
class CSVLoader(ProductLoader)
```

Loader for CSV product data.

Supports column mapping from CSV headers to ProductSpec fields.
Automatically parses JSON columns (features, faqs, specs, product_variants, etc.).

Example CSV (new format):
    product_url,product_name,price,description,image_url,features,faqs,footprint_sqft,
    product_variants,specs,product_json,product_data,document

Usage:
    loader = CSVLoader(
        catalog=my_catalog,
        column_mapping={
            "product_name": "name",
            "product_url": "url",
        },
        json_columns=["features", "faqs", "specs", "product_variants", "product_json", "product_data"]
    )
    result = await loader.load_file("products.csv")

## Methods

- `async def load_file(self, file_path: Union[str, Path]) -> LoadResult` — Load products from a CSV file.
