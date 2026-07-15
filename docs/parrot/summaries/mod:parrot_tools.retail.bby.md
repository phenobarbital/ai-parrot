---
type: Wiki Summary
title: parrot_tools.retail.bby
id: mod:parrot_tools.retail.bby
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: BestBuy API Toolkit - Unified toolkit for BestBuy operations.
relates_to:
- concept: class:parrot_tools.retail.bby.BestBuyToolkit
  rel: defines
- concept: class:parrot_tools.retail.bby.ProductAvailabilityInput
  rel: defines
- concept: class:parrot_tools.retail.bby.ProductSearchInput
  rel: defines
- concept: class:parrot_tools.retail.bby.StoreLocatorInput
  rel: defines
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.retail.bby`

BestBuy API Toolkit - Unified toolkit for BestBuy operations.

Provides methods for:
- Product search and information
- Store availability checking
- Inventory lookup

## Classes

- **`ProductSearchInput(BaseModel)`** — Input schema for product search.
- **`ProductAvailabilityInput(BaseModel)`** — Input schema for checking product availability.
- **`StoreLocatorInput(BaseModel)`** — Input schema for finding stores.
- **`BestBuyToolkit(AbstractToolkit)`** — Toolkit for interacting with BestBuy API and services.
