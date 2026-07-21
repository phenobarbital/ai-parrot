---
type: Wiki Summary
title: parrot.advisors.tools.search
id: mod:parrot.advisors.tools.search
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Product Search Tool - Direct product lookup and search.
relates_to:
- concept: class:parrot.advisors.tools.search.GetProductDetailsTool
  rel: defines
- concept: class:parrot.advisors.tools.search.SearchProductsArgs
  rel: defines
- concept: class:parrot.advisors.tools.search.SearchProductsTool
  rel: defines
- concept: mod:parrot.advisors.models
  rel: references
- concept: mod:parrot.advisors.tools.base
  rel: references
---

# `parrot.advisors.tools.search`

Product Search Tool - Direct product lookup and search.

## Classes

- **`SearchProductsArgs(ProductAdvisorToolArgs)`** — Arguments for searching products.
- **`SearchProductsTool(BaseAdvisorTool)`** — Search for products by name, category, or keywords.
- **`GetProductDetailsTool(BaseAdvisorTool)`** — Get detailed information about a specific product.
