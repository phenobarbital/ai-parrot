---
type: Wiki Summary
title: parrot.advisors.catalog.catalog
id: mod:parrot.advisors.catalog.catalog
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ProductCatalog - Abstraction over PgVectorStore for product management.
relates_to:
- concept: class:parrot.advisors.catalog.catalog.ProductCatalog
  rel: defines
- concept: class:parrot.advisors.catalog.catalog.ProductSearchResult
  rel: defines
- concept: mod:parrot.advisors.catalog.schema
  rel: references
- concept: mod:parrot.advisors.models
  rel: references
- concept: mod:parrot.advisors.tools.utils
  rel: references
- concept: mod:parrot.models.stores
  rel: references
- concept: mod:parrot.stores.postgres
  rel: references
---

# `parrot.advisors.catalog.catalog`

ProductCatalog - Abstraction over PgVectorStore for product management.

Provides:
- Product CRUD with automatic embedding generation
- Structured filtering + semantic search
- Comparison utilities
- Multi-tenant support via catalog_id

## Classes

- **`ProductSearchResult`** — Enhanced search result with product-specific fields.
- **`ProductCatalog`** — Product catalog with hybrid search capabilities.
