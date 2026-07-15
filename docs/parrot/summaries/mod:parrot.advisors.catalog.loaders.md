---
type: Wiki Summary
title: parrot.advisors.catalog.loaders
id: mod:parrot.advisors.catalog.loaders
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Loaders for ingesting product data into ProductCatalog.
relates_to:
- concept: class:parrot.advisors.catalog.loaders.CSVLoader
  rel: defines
- concept: class:parrot.advisors.catalog.loaders.JSONMarkdownLoader
  rel: defines
- concept: class:parrot.advisors.catalog.loaders.LoadResult
  rel: defines
- concept: class:parrot.advisors.catalog.loaders.ProductLoader
  rel: defines
- concept: class:parrot.advisors.catalog.loaders.SeparateMarkdownLoader
  rel: defines
- concept: mod:parrot.advisors.models
  rel: references
---

# `parrot.advisors.catalog.loaders`

Loaders for ingesting product data into ProductCatalog.

Supports:
- JSON with embedded markdown
- JSON + separate markdown files
- Structured JSON only

## Classes

- **`LoadResult`** — Result of a load operation.
- **`ProductLoader`** — Base loader for product data.
- **`JSONMarkdownLoader(ProductLoader)`** — Loader for JSON files with embedded markdown descriptions.
- **`SeparateMarkdownLoader(ProductLoader)`** — Loader for JSON specs + separate markdown files.
- **`CSVLoader(ProductLoader)`** — Loader for CSV product data.
