---
type: Wiki Entity
title: EpsonProductToolkit
id: class:parrot_tools.epson.EpsonProductToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for managing Epson-related operations.
relates_to:
- concept: class:parrot_tools.querytoolkit.QueryToolkit
  rel: extends
---

# EpsonProductToolkit

Defined in [`parrot_tools.epson`](../summaries/mod:parrot_tools.epson.md).

```python
class EpsonProductToolkit(QueryToolkit)
```

Toolkit for managing Epson-related operations.

This toolkit provides tools to:
- get_product_information: Get basic product information.

## Methods

- `async def get_product_information(self, model: str, product_name: Optional[str]=None, output_format: str='structured', structured_obj: Optional[ProductInfo]=ProductInfo) -> ProductInfo` — Retrieve product information for a given Epson product Model.
