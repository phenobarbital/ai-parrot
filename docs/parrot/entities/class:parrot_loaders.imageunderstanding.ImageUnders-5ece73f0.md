---
type: Wiki Entity
title: ImageUnderstandingLoader
id: class:parrot_loaders.imageunderstanding.ImageUnderstandingLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Image analysis loader using Google GenAI for understanding image content.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# ImageUnderstandingLoader

Defined in [`parrot_loaders.imageunderstanding`](../summaries/mod:parrot_loaders.imageunderstanding.md).

```python
class ImageUnderstandingLoader(AbstractLoader)
```

Image analysis loader using Google GenAI for understanding image content.
Extracts descriptions, text, objects, and structured information from images.
Uses the flash preview image model for analysis.

## Methods

- `async def close(self)` — Clean up resources.
