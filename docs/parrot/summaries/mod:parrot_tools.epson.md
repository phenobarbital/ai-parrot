---
type: Wiki Summary
title: parrot_tools.epson
id: mod:parrot_tools.epson
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_tools.epson
relates_to:
- concept: class:parrot_tools.epson.EpsonProductToolkit
  rel: defines
- concept: class:parrot_tools.epson.ProductInfo
  rel: defines
- concept: class:parrot_tools.epson.ProductInput
  rel: defines
- concept: mod:parrot.exceptions
  rel: references
---

# `parrot_tools.epson`

## Classes

- **`ProductInput(BaseModel)`** — Input schema for querying Epson product information.
- **`ProductInfo(BaseModel)`** — Schema for the product information returned by the query.
- **`EpsonProductToolkit(QueryToolkit)`** — Toolkit for managing Epson-related operations.
