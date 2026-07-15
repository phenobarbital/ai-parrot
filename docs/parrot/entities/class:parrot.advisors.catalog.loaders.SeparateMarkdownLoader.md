---
type: Wiki Entity
title: SeparateMarkdownLoader
id: class:parrot.advisors.catalog.loaders.SeparateMarkdownLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Loader for JSON specs + separate markdown files.
relates_to:
- concept: class:parrot.advisors.catalog.loaders.ProductLoader
  rel: extends
---

# SeparateMarkdownLoader

Defined in [`parrot.advisors.catalog.loaders`](../summaries/mod:parrot.advisors.catalog.loaders.md).

```python
class SeparateMarkdownLoader(ProductLoader)
```

Loader for JSON specs + separate markdown files.

Expects:
- products.json with basic specs
- products/{id}.md for each product's full description

## Methods

- `async def load_file(self, file_path: Union[str, Path]) -> LoadResult` — Load products and their markdown descriptions.
