---
type: Wiki Summary
title: parrot_tools.products
id: mod:parrot_tools.products
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.products
relates_to:
- concept: class:parrot_tools.products.ProductInfo
  rel: defines
- concept: class:parrot_tools.products.ProductInfoTool
  rel: defines
- concept: class:parrot_tools.products.ProductInput
  rel: defines
- concept: class:parrot_tools.products.ProductListInput
  rel: defines
- concept: class:parrot_tools.products.ProductListTool
  rel: defines
- concept: class:parrot_tools.products.ProductResponse
  rel: defines
- concept: mod:parrot._imports
  rel: references
---

# `parrot_tools.products`

## Classes

- **`ProductInput(BaseModel)`** — Input schema for product information requests.
- **`ProductInfo(BaseModel)`** — Schema for the product information returned by the query.
- **`ProductInfoTool(AbstractTool)`** — Tool to get detailed information about a specific product model.
- **`ProductListInput(BaseModel)`** — Input schema for product list requests.
- **`ProductListTool(AbstractTool)`** — Tool to get list of products for a given program/tenant.
- **`ProductResponse(Model)`** — ProductResponse is a model that defines the structure of the response for Product agents.
