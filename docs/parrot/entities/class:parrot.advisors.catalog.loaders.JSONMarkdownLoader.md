---
type: Wiki Entity
title: JSONMarkdownLoader
id: class:parrot.advisors.catalog.loaders.JSONMarkdownLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Loader for JSON files with embedded markdown descriptions.
relates_to:
- concept: class:parrot.advisors.catalog.loaders.ProductLoader
  rel: extends
---

# JSONMarkdownLoader

Defined in [`parrot.advisors.catalog.loaders`](../summaries/mod:parrot.advisors.catalog.loaders.md).

```python
class JSONMarkdownLoader(ProductLoader)
```

Loader for JSON files with embedded markdown descriptions.
    
    Format:
    {
        "products": [
            {
                "id": "shed-001",
                "name": "Classic Shed",
                "specs": {...},
                "description": "# Full Markdown Content

..."
            }
        ]
    }
